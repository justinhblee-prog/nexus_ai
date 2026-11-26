import os
import sqlite3
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

DB_PATH = "data/studio_data.db"
HTTP_HEADERS = {"User-Agent": "NEXUS-STUDIO-PRO/1.0 (trend research)"}
REQUEST_TIMEOUT = 8


def init_radar_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS trend_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period_type TEXT, region TEXT,
        rank_no INTEGER, is_global_top10 INTEGER, topic TEXT, matched_channel TEXT,
        source_name TEXT, source_url TEXT, est_views INTEGER, avg_cat_views INTEGER,
        growth_pct INTEGER, viral_score INTEGER, ai_reason TEXT, created_at TEXT
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
    endpoint = "https://hacker-news.firebaseio.com/v0"
    try:
        response = requests.get(f"{endpoint}/topstories.json", headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT)
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


def scan_global_trends(period_type="daily"):
    if period_type not in ("daily", "weekly"):
        raise ValueError("period_type must be 'daily' or 'weekly'")

    feeds = [
        ("KR", "Google News KR", "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko"),
        ("US", "Google News US", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
        ("JP", "Google News JP", "https://news.google.com/rss?hl=ja&gl=JP&ceid=JP:ja"),
        ("GB", "Google News UK", "https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en"),
        ("GB", "BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
    ]
    by_geo = {"KR": [], "US": [], "JP": [], "GB": []}
    hn_items, hn_error = _fetch_hn()
    by_geo["US"] = hn_items
    source_results = [("US", "Hacker News", "https://hacker-news.firebaseio.com/v0/topstories.json",
                       hn_items, hn_error)]
    with ThreadPoolExecutor(max_workers=len(feeds)) as executor:
        futures = [executor.submit(_parse_rss_safe, geo, label, url) for geo, label, url in feeds]
        for future, (geo, label, url) in zip(futures, feeds):
            items, error = future.result()
            source_results.append((geo, label, url, items, error))
            for item in items:
                if not any(existing[1] == item[1] for existing in by_geo[geo]):
                    by_geo[geo].append(item)

    all_items = []
    for geo in ("KR", "US", "JP", "GB"):
        for rank, item in enumerate(by_geo[geo][:10], start=1):
            _, topic, source, url, source_score = item
            # RSS feeds do not provide comparable view/growth data. Keep those fields NULL.
            # Hacker News points are retained as the only source-provided popularity signal.
            viral_score = source_score if source_score is not None else 0
            all_items.append({
                "region": geo, "rank_no": rank, "is_global_top10": 0,
                "topic": topic, "matched_channel": match_ch(topic),
                "source_name": source, "source_url": url,
                "est_views": None, "avg_cat_views": None, "growth_pct": None,
                "viral_score": viral_score,
            })

    # A cross-source global top ten is only defensible when comparable source scores exist.
    scored = [item for item in all_items if item["viral_score"] > 0]
    for global_rank, item in enumerate(sorted(scored, key=lambda row: row["viral_score"], reverse=True)[:10], start=1):
        item["is_global_top10"] = global_rank

    conn = init_radar_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for region, source_name, source_url, items, error in source_results:
            record_source_health(conn, region, source_name, source_url,
                                 success=error is None, item_count=len(items), error=error, now=now)
        if all_items:
            conn.execute("DELETE FROM trend_recommendations WHERE period_type=?", (period_type,))
            for item in all_items:
                reason = f"[{item['region']} #{item['rank_no']}] {item['source_name']} source ranking"
                conn.execute(
                    """INSERT INTO trend_recommendations
                    (period_type, region, rank_no, is_global_top10, topic, matched_channel,
                     source_name, source_url, est_views, avg_cat_views, growth_pct, viral_score,
                     ai_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (period_type, item["region"], item["rank_no"], item["is_global_top10"],
                     item["topic"], item["matched_channel"], item["source_name"], item["source_url"],
                     item["est_views"], item["avg_cat_views"], item["growth_pct"], item["viral_score"],
                     reason, now),
                )
        conn.commit()
        return all_items
    finally:
        conn.close()
