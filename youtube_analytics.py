"""Read-only YouTube Analytics integration; metrics are never estimated."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import os
import time

from oauth_config import ANALYTICS_SCOPES, get_channel_token_path


_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
)
_CACHE_TTL_SECONDS = 900
_CACHE = {"key": None, "at": 0.0, "value": None}


def clear_platform_metrics_cache():
    _CACHE.update({"key": None, "at": 0.0, "value": None})


def _load_credentials(token_path):
    from google.oauth2.credentials import Credentials
    return Credentials.from_authorized_user_file(token_path)


def _refresh_credentials(credentials, token_path):
    from google.auth.transport.requests import Request
    credentials.refresh(Request())
    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())


def _build_clients(credentials):
    from googleapiclient.discovery import build
    analytics = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    return analytics, youtube


def _number(value, integer=False):
    try:
        number = float(value or 0)
        return int(number) if integer else number
    except (TypeError, ValueError):
        return 0 if integer else 0.0


def _query_channel(channel_name, start_date, end_date):
    token_path = get_channel_token_path(channel_name)
    if not os.path.isfile(token_path):
        return {"channel": channel_name, "status": "not_connected"}

    credentials = _load_credentials(token_path)
    if not credentials.has_scopes(ANALYTICS_SCOPES):
        return {"channel": channel_name, "status": "scope_required"}
    if credentials.expired:
        if not credentials.refresh_token:
            return {"channel": channel_name, "status": "reauth_required"}
        _refresh_credentials(credentials, token_path)

    analytics, youtube = _build_clients(credentials)
    report = analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=",".join(_METRICS),
    ).execute()
    headers = [column.get("name") for column in report.get("columnHeaders", [])]
    row = (report.get("rows") or [])[0] if report.get("rows") else []
    values = dict(zip(headers, row))

    channel_response = youtube.channels().list(part="statistics", mine=True).execute()
    channel_items = channel_response.get("items") or []
    statistics = (channel_items[0].get("statistics") or {}) if channel_items else {}
    subscriber_count = None
    if statistics and not statistics.get("hiddenSubscriberCount", False):
        subscriber_count = _number(statistics.get("subscriberCount"), integer=True)

    metrics = {
        "views_28d": _number(values.get("views"), integer=True),
        "watch_minutes_28d": _number(values.get("estimatedMinutesWatched")),
        "average_view_duration_seconds": _number(values.get("averageViewDuration")),
        "likes_28d": _number(values.get("likes"), integer=True),
        "comments_28d": _number(values.get("comments"), integer=True),
        "shares_28d": _number(values.get("shares"), integer=True),
        "subscribers_gained_28d": _number(values.get("subscribersGained"), integer=True),
        "subscribers_lost_28d": _number(values.get("subscribersLost"), integer=True),
        "subscriber_count": subscriber_count,
    }
    return {"channel": channel_name, "status": "connected", **metrics}


def _empty_result(status, channel_statuses, start_date, end_date, note):
    return {
        "status": status,
        "period_days": 28,
        "period_start": start_date,
        "period_end": end_date,
        "subscriber_count": None,
        "views": None,
        "views_28d": None,
        "watch_minutes_28d": None,
        "average_view_duration_seconds": None,
        "engagement_rate": None,
        "subscribers_gained_28d": None,
        "subscribers_lost_28d": None,
        "revenue": None,
        "revenue_status": "monetary_scope_not_requested",
        "source": None,
        "updated_at": None,
        "channels": channel_statuses,
        "note": note,
    }


def get_platform_metrics(channel_names, force_refresh=False):
    names = tuple(sorted({str(name).strip() for name in channel_names if str(name).strip()}))
    today = date.today()
    end_date = today - timedelta(days=2)  # avoid incomplete provider reporting days
    start_date = end_date - timedelta(days=27)
    start_text, end_text = start_date.isoformat(), end_date.isoformat()

    if not names:
        return _empty_result("not_connected", [], start_text, end_text, "No YouTube channels are configured.")

    now = time.time()
    if (not force_refresh and _CACHE["key"] == names and _CACHE["value"] is not None
            and now - _CACHE["at"] < _CACHE_TTL_SECONDS):
        return deepcopy(_CACHE["value"])

    channel_results = []
    for channel_name in names:
        try:
            channel_results.append(_query_channel(channel_name, start_text, end_text))
        except Exception as exc:
            channel_results.append({
                "channel": channel_name,
                "status": "error",
                "error_type": type(exc).__name__,
            })

    connected = [item for item in channel_results if item["status"] == "connected"]
    missing_scope = any(item["status"] in ("scope_required", "reauth_required") for item in channel_results)
    missing_token = any(item["status"] == "not_connected" for item in channel_results)
    errors = any(item["status"] == "error" for item in channel_results)

    if not connected:
        if missing_scope:
            status = "scope_required"
            note = "Reauthorize each channel in Streamlit and grant YouTube Analytics read-only plus YouTube read-only access."
        elif errors:
            status = "error"
            note = "YouTube Analytics could not be queried. Inspect per-channel status and OAuth/API configuration."
        else:
            status = "not_connected"
            note = "No channel OAuth tokens are connected. Platform metrics are not estimated."
        return _empty_result(status, channel_results, start_text, end_text, note)

    totals = {
        key: sum(_number(item.get(key)) for item in connected)
        for key in (
            "views_28d", "watch_minutes_28d", "likes_28d", "comments_28d",
            "shares_28d", "subscribers_gained_28d", "subscribers_lost_28d",
        )
    }
    total_views = totals["views_28d"]
    average_duration = (
        sum(_number(item.get("average_view_duration_seconds")) * _number(item.get("views_28d")) for item in connected)
        / total_views if total_views else 0.0
    )
    subscriber_values = [item["subscriber_count"] for item in connected if item.get("subscriber_count") is not None]
    engagement_count = totals["likes_28d"] + totals["comments_28d"] + totals["shares_28d"]
    engagement_rate = engagement_count / total_views * 100 if total_views else 0.0
    status = "partial" if missing_scope or missing_token or errors else "connected"
    note = "Actual YouTube Analytics API data for the latest complete 28-day window. Revenue is omitted until a separate monetary permission is explicitly enabled."
    if status == "partial":
        note += " Some channels are not connected or require renewed read-only consent."

    result = {
        "status": status,
        "period_days": 28,
        "period_start": start_text,
        "period_end": end_text,
        "subscriber_count": sum(subscriber_values) if subscriber_values else None,
        "views": int(total_views),
        **totals,
        "average_view_duration_seconds": average_duration,
        "engagement_rate": engagement_rate,
        "revenue": None,
        "revenue_status": "monetary_scope_not_requested",
        "source": "YouTube Analytics API",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channels": channel_results,
        "note": note,
    }
    _CACHE.update({"key": names, "at": now, "value": deepcopy(result)})
    return result
