"""Read-only connectivity diagnostic for configured Discovery feeds."""
import json
from concurrent.futures import ThreadPoolExecutor

import requests

from trend_radar import (
    HN_TOP_STORIES_URL,
    HTTP_HEADERS,
    REQUEST_TIMEOUT,
    RSS_FEEDS,
    _parse_rss_safe,
)


def check_rss(source):
    region, label, url = source
    items, error = _parse_rss_safe(region, label, url)
    return {
        "source": label,
        "region": region,
        "url": url,
        "ok": error is None and bool(items),
        "items": len(items),
        "error": error,
    }


def check_hacker_news():
    try:
        response = requests.get(
            HN_TOP_STORIES_URL,
            headers=HTTP_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        stories = response.json()
        if not isinstance(stories, list) or not stories:
            raise ValueError("top stories response was empty or not a list")
        return {
            "source": "Hacker News",
            "region": "US",
            "url": HN_TOP_STORIES_URL,
            "ok": True,
            "items": len(stories),
            "error": None,
        }
    except (requests.RequestException, ValueError) as exc:
        return {
            "source": "Hacker News",
            "region": "US",
            "url": HN_TOP_STORIES_URL,
            "ok": False,
            "items": 0,
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }


def main():
    with ThreadPoolExecutor(max_workers=len(RSS_FEEDS) + 1) as pool:
        futures = [pool.submit(check_rss, source) for source in RSS_FEEDS]
        futures.append(pool.submit(check_hacker_news))
        results = [future.result() for future in futures]
    report = {
        "ok": all(item["ok"] for item in results),
        "successful_sources": sum(item["ok"] for item in results),
        "total_sources": len(results),
        "sources": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
