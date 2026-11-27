import os
import json
import sqlite3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

DB_PATH = "data/studio_data.db"
HTTP_HEADERS = {"User-Agent": "NEXUS-STUDIO-PRO/1.0 (trend research)"}
REQUEST_TIMEOUT = 8
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
HN_TOP_STORIES_URL = f"{HN_API_BASE}/topstories.json"
RSS_FEEDS = (
    ("KR", "Google News KR", "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"),
    ("US", "Google News US", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
    ("JP", "Google News JP", "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"),
    ("GB", "Google News UK", "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en"),
    ("GB", "BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
)


def init_radar_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS trend_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period_type TEXT, region TEXT,
        rank_no INTEGER, source_rank INTEGER, is_global_top10 INTEGER, topic TEXT, matched_channel TEXT,
        source_name TEXT, source_url TEXT, source_score INTEGER, source_score_label TEXT,
        est_views INTEGER, avg_cat_views INTEGER, growth_pct INTEGER, viral_score INTEGER,
        ai_reason TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS auto_produced_topics (
        topic TEXT PRIMARY KEY, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS source_health (
        source_name TEXT PRIMARY KEY, region TEXT NOT NULL, source_url TEXT NOT NULL,
        last_attempt_at TEXT, last_success_at TEXT, last_status TEXT NOT NULL DEFAULT 'unknown',
        item_count INTEGER NOT NULL DEFAULT 0, consecutive_failures INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS radar_scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period_type TEXT NOT NULL,
        started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
        item_count INTEGER NOT NULL DEFAULT 0, successful_sources INTEGER NOT NULL DEFAULT 0,
        failed_sources INTEGER NOT NULL DEFAULT 0, source_summary_json TEXT NOT NULL DEFAULT '{}'
    )""")
    recommendation_columns = {row[1] for row in conn.execute("PRAGMA table_info(trend_recommendations)")}
    for column, definition in (
        ("source_rank", "INTEGER"),
        ("source_score", "INTEGER"),
        ("source_score_label", "TEXT"),
    ):
        if column not in recommendation_columns:
            conn.execute(f"ALTER TABLE trend_recommendations ADD COLUMN {column} {definition}")
    conn.commit()
    return conn


def match_ch(title):
    low = title.lower()
    if any(k in low for k in ["ai", "gpt", "tech", "chip", "robot", "인공지능", "반도체", "로봇", "테크", "양자"]):
        return "Future Leak"
    if any(k in low for k in ["economy", "stock", "market", "fed", "bank", "경제", "증시", "금리", "환율", "투자", "금융"]):
        return "Money Glitch"
    if any(k in low for k in ["health", "sleep", "cancer", "doctor", "건강", "수면", "병원", "운동"]):
        return "30Sec Shift"
    if any(k in low for k in ["space", "nasa", "secret", "crime", "우주", "미스터리", "사건", "발견"]):
        return "Dark Files Global"
    # Stable fallback: do not randomly reassign a topic on each scan.
    return "Brain Glitch"


def _local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _parse_rss_safe(geo, label, url):
    items = []
    error = None
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        for entry in root.iter():
            if _local_name(entry.tag) not in ("item", "entry"):
                continue
            title = ""
            link = ""
            for child in list(entry):
                name = _local_name(child.tag)
                if name == "title" and not title:
                    title = "".join(child.itertext()).strip()
                elif name == "link" and not link:
                    link = (child.attrib.get("href") or "".join(child.itertext())).strip()
            if title and link.startswith("http"):
                items.append((geo, title, label, link, None))
            if len(items) >= 12:
                break
    except (requests.RequestException, ET.ParseError, ValueError) as exc:
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"RSS source unavailable [{label}]: {error}")
    return items, error


def record_source_health(conn, region, source_name, source_url, success, item_count, error=None, now=None):
    stamp = now or datetime.now().isoformat(timespec="seconds")
    previous = conn.execute(
        "SELECT last_success_at, consecutive_failures FROM source_health WHERE source_name=?",
        (source_name,),
    ).fetchone()
    last_success = stamp if success else (previous[0] if previous else None)
    failures = 0 if success else ((previous[1] if previous else 0) + 1)
    conn.execute(
        """INSERT OR REPLACE INTO source_health
           (source_name, region, source_url, last_attempt_at, last_success_at, last_status,
            item_count, consecutive_failures, last_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_name, region, source_url, stamp, last_success,
         "success" if success else "failed", int(item_count), failures,
         None if success else (str(error or "no_items")[:500])),
    )


def _fetch_hn():
    endpoint = HN_API_BASE
    try:
        response = requests.get(HN_TOP_STORIES_URL, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        story_ids = response.json()[:12]
    except (requests.RequestException, ValueError) as exc:
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"Hacker News top stories unavailable: {error}")
        return [], error

    def fetch_one(story_id):
        try:
            response = requests.get(f"{endpoint}/item/{story_id}.json", headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            item = response.json()
            if item and item.get("title"):
                url = item.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                return ("US", item["title"], "Hacker News", url, int(item.get("score") or 0))
        except (requests.RequestException, ValueError, TypeError) as exc:
            print(f"Hacker News item {story_id} unavailable: {exc}")
        return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        items = [item for item in executor.map(fetch_one, story_ids) if item]
    return items, None


def get_source_health():
    conn = init_radar_db()
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(
            """SELECT source_name, region, source_url, last_attempt_at, last_success_at,
                      last_status, item_count, consecutive_failures, last_error
               FROM source_health ORDER BY region, source_name"""
        ).fetchall()]
    finally:
        conn.close()


def get_scan_status(period_type="daily"):
    if period_type not in ("daily", "weekly"):
        raise ValueError("period_type must be 'daily' or 'weekly'")
    conn = init_radar_db()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM radar_scans WHERE period_type=? ORDER BY id DESC LIMIT 1",
            (period_type,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["source_summary"] = json.loads(result.pop("source_summary_json") or "{}")
        except (TypeError, ValueError):
            result["source_summary"] = {}
        return result
    finally:
        conn.close()


def scan_global_trends(period_type="daily"):
    if period_type not in ("daily", "weekly"):
        raise ValueError("period_type must be 'daily' or 'weekly'")

    started_at = datetime.now().isoformat(timespec="seconds")
    scan_conn = init_radar_db()
    scan_cursor = scan_conn.execute(
        """INSERT INTO radar_scans (period_type, started_at, status)
           VALUES (?, ?, 'running')""",
        (period_type, started_at),
    )
    scan_id = scan_cursor.lastrowid
    scan_conn.commit()
    scan_conn.close()

    feeds = RSS_FEEDS
    hn_url = HN_TOP_STORIES_URL
    hn_items, hn_error = _fetch_hn()
    source_results = [("US", "Hacker News", hn_url, hn_items, hn_error)]
    try:
        with ThreadPoolExecutor(max_workers=len(feeds)) as executor:
            futures = [executor.submit(_parse_rss_safe, geo, label, url) for geo, label, url in feeds]
            for future, (geo, label, url) in zip(futures, feeds):
                items, error = future.result()
                source_results.append((geo, label, url, items, error))

        all_items = []
        region_ranks = {"KR": 0, "US": 0, "JP": 0, "GB": 0}
        seen = set()
        for geo, source_name, source_url, items, source_error in source_results:
            if source_error is not None or not items:
                continue
            for source_rank, item in enumerate(items, start=1):
                _, topic, _source, url, source_score = item
                dedupe_key = (geo, topic.casefold())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                region_ranks[geo] += 1
                all_items.append({
                    "region": geo,
                    "rank_no": source_rank,
                    "source_rank": source_rank,
                    "is_global_top10": 0,
                    "topic": topic,
                    "matched_channel": match_ch(topic),
                    "source_name": source_name,
                    "source_url": url or source_url,
                    "source_score": source_score,
                    "source_score_label": "Hacker News points" if source_score is not None else None,
                    "est_views": None,
                    "avg_cat_views": None,
                    "growth_pct": None,
                    "viral_score": None,
                })

        conn = init_radar_db()
        try:
            successful_sources = 0
            failed_sources = 0
            source_summary = {}
            now = datetime.now().isoformat(timespec="seconds")
            for region, source_name, source_url, items, error in source_results:
                success = error is None and bool(items)
                health_error = None if success else (error or "no_items")
                record_source_health(conn, region, source_name, source_url,
                                     success=success, item_count=len(items),
                                     error=health_error, now=now)
                status = "success" if success else "failed"
                source_summary[source_name] = {
                    "region": region,
                    "status": status,
                    "item_count": len(items),
                    "error": health_error,
                }
                successful_sources += int(success)
                failed_sources += int(not success)

            if all_items:
                # Replace only sources that completed successfully; retain prior rows for
                # failed feeds and expose their stale status through source health metadata.
                for source_name, details in source_summary.items():
                    if details["status"] == "success":
                        conn.execute(
                            "DELETE FROM trend_recommendations WHERE period_type=? AND source_name=?",
                            (period_type, source_name),
                        )
                for item in all_items:
                    reason = f"[{item['region']}] {item['source_name']} source order #{item['source_rank']}"
                    conn.execute(
                        """INSERT INTO trend_recommendations
                        (period_type, region, rank_no, source_rank, is_global_top10, topic,
                         matched_channel, source_name, source_url, source_score, source_score_label,
                         est_views, avg_cat_views, growth_pct, viral_score, ai_reason, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (period_type, item["region"], item["rank_no"], item["source_rank"],
                         item["is_global_top10"], item["topic"], item["matched_channel"],
                         item["source_name"], item["source_url"], item["source_score"],
                         item["source_score_label"], item["est_views"], item["avg_cat_views"],
                         item["growth_pct"], item["viral_score"], reason, now),
                    )

            status = "success" if failed_sources == 0 and all_items else (
                "partial" if all_items else "failed"
            )
            conn.execute(
                """UPDATE radar_scans SET completed_at=?, status=?, item_count=?,
                   successful_sources=?, failed_sources=?, source_summary_json=? WHERE id=?""",
                (now, status, len(all_items), successful_sources, failed_sources,
                 json.dumps(source_summary, ensure_ascii=False, sort_keys=True), scan_id),
            )
            conn.commit()
        finally:
            conn.close()
        return all_items
    except Exception as exc:
        failed_at = datetime.now().isoformat(timespec="seconds")
        conn = init_radar_db()
        try:
            conn.execute(
                """UPDATE radar_scans SET completed_at=?, status='failed',
                   source_summary_json=? WHERE id=?""",
                (failed_at, json.dumps({"scan_error": type(exc).__name__}), scan_id),
            )
            conn.commit()
        finally:
            conn.close()
        raise
