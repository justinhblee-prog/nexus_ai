"""Read-only adapter for shared public trend data in Supabase."""
from __future__ import annotations


def read_shared_trends(client, limit: int = 30) -> dict:
    """Return the latest daily public feed without consulting serverless local files."""
    rows = client.select("public_trend_signals", {
        "select": "region,rank_no,topic,source_name,source_url,source_score,source_score_label,growth_pct,viral_score,ai_reason,created_at",
        "period_type": "eq.daily",
        "order": "rank_no.asc,created_at.desc",
        "limit": str(max(1, min(100, int(limit) * 3))),
    }) or []
    items = []
    seen = set()
    for row in rows:
        item = dict(row)
        topic = str(item.get("topic") or "").strip()
        normalized = " ".join(topic.casefold().split())
        if not topic or normalized in seen:
            continue
        seen.add(normalized)
        source_url = str(item.get("source_url") or "")
        item["source_url"] = source_url if source_url.startswith("https://") else None
        items.append(item)
        if len(items) >= limit:
            break

    scans = client.select("public_trend_scans", {
        "select": "status,completed_at,item_count,successful_sources,failed_sources,source_summary,updated_at",
        "period_type": "eq.daily",
        "limit": "1",
    }) or []
    scan = scans[0] if scans else {
        "status": "not_scanned",
        "completed_at": None,
        "item_count": 0,
        "successful_sources": 0,
        "failed_sources": 0,
        "source_summary": {},
        "updated_at": None,
    }
    return {
        "items": items,
        "scan": scan,
        "scope": "shared_public_signals",
        "available": bool(scans or items),
    }
