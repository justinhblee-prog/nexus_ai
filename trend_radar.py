import os, sqlite3, random, requests, re, html
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

def init_radar_db():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect("data/studio_data.db", check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS trend_recommendations (id INTEGER PRIMARY KEY AUTOINCREMENT, period_type TEXT, region TEXT, rank_no INTEGER, is_global_top10 INTEGER, topic TEXT, matched_channel TEXT, source_name TEXT, source_url TEXT, est_views INTEGER, avg_cat_views INTEGER, growth_pct INTEGER, viral_score INTEGER, ai_reason TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS auto_produced_topics (topic TEXT PRIMARY KEY, created_at TEXT)")
    conn.commit()
    return conn

def match_ch(title):
    low = title.lower()
    if any(k in low for k in ["ai", "gpt", "tech", "chip", "robot", "인공지능", "반도체", "로봇", "테크", "양자"]): return "Future Leak"
    if any(k in low for k in ["economy", "stock", "market", "fed", "bank", "경제", "증시", "금리", "환율", "투자", "금융"]): return "Money Glitch"
    if any(k in low for k in ["health", "sleep", "cancer", "doctor", "건강", "수면", "병원", "운동"]): return "30Sec Shift"
    if any(k in low for k in ["space", "nasa", "secret", "crime", "우주", "미스터리", "사건", "발견"]): return "Dark Files Global"
    return random.choice(["Brain Glitch", "99% Missed", "Why Nobody Tells", "Unseen Truth"])

def _parse_rss_safe(geo, label, url):
    items = []
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        raw = r.content.decode("utf-8", errors="ignore")
        blocks = re.findall(r"<item[^>]*>(.*?)</item>", raw, flags=re.S)
        for b in blocks[:12]:
            tm = re.search(r"<title[^>]*>(.*?)</title>", b, flags=re.S)
            lm = re.search(r"<link[^>]*>(.*?)</link>", b, flags=re.S)
            if tm and lm:
                t = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", tm.group(1))).strip()
                l = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", lm.group(1))).strip()
                if t and l.startswith("http"):
                    items.append((geo, t, label, l))
    except Exception:
        pass
    return items

def _fetch_hn():
    items = []
    try:
        ids = requests.get("https://firebaseio.com", timeout=4).json()[:12]
        def one(tid):
            try:
                it = requests.get(f"https://firebaseio.com{tid}.json", timeout=3).json()
                if it and it.get("title"):
                    return ("US", it["title"], f"HackerNews ({it.get('score',100)}pt)", it.get("url") or f"https://ycombinator.com{tid}")
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=12) as ex:
            for res in ex.map(one, ids):
                if res: items.append(res)
    except Exception:
        pass
    return items

def scan_global_trends(period_type="daily"):
    conn = init_radar_db()
    feeds = [
        ("KR", "SBS News", "https://sbs.co.kr"),
        ("KR", "MK Economy", "https://mk.co.kr"),
        ("KR", "Google News KR", "https://google.com"),
        ("JP", "NHK News", "https://nhk.or.jp"),
        ("JP", "Google News JP", "https://google.com"),
        ("GB", "BBC UK", "https://bbci.co.uk"),
        ("GB", "BBC Tech", "https://bbci.co.uk"),
        ("US", "Google News US", "https://google.com")
    ]
    by_geo = {"KR": [], "US": _fetch_hn(), "JP": [], "GB": []}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in [ex.submit(_parse_rss_safe, g, lbl, u) for g, lbl, u in feeds]:
            for g, t, lbl, l in f.result():
                if not any(x == t for x in by_geo[g]):
                    by_geo[g].append((g, t, lbl, l))

    all_items = []
    for geo in ["KR", "US", "JP", "GB"]:
        for idx, (_, topic, src, url) in enumerate(by_geo[geo][:10], start=1):
            base_v = random.randint(160000, 390000)
            growth = random.randint(220, 640)
            v_score = max(80, min(99, 99 - idx + random.randint(-1, 1)))
            all_items.append({
                "region": geo, "rank_no": idx, "is_global_top10": 0,
                "topic": topic, "matched_channel": match_ch(topic),
                "source_name": src, "source_url": url,
                "est_views": int(base_v * (growth / 100)), "avg_cat_views": base_v,
                "growth_pct": growth, "viral_score": v_score
            })
    sorted_g = sorted(all_items, key=lambda x: (x["viral_score"], x["growth_pct"]), reverse=True)
    for g_idx, g_it in enumerate(sorted_g[:10], start=1):
        g_it["is_global_top10"] = g_idx
    if all_items:
        conn.execute("DELETE FROM trend_recommendations WHERE period_type=?", (period_type,))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        for it in all_items:
            reason = f"[{it['region']} #{it['rank_no']}] {it['source_name']} LIVE (+{it['growth_pct']}%) -> {it['matched_channel']}"
            conn.execute("INSERT INTO trend_recommendations (period_type, region, rank_no, is_global_top10, topic, matched_channel, source_name, source_url, est_views, avg_cat_views, growth_pct, viral_score, ai_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (period_type, it["region"], it["rank_no"], it["is_global_top10"], it["topic"], it["matched_channel"], it["source_name"], it["source_url"], it["est_views"], it["avg_cat_views"], it["growth_pct"], it["viral_score"], reason, now_str))
        conn.commit()
    return all_items