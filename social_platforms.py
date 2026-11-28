"""Provider capability catalogue for the NEXUS multi-account social workspace.

Only providers with a complete server-side OAuth adapter are marked connectable.
A provider being listed does not imply that its publishing API has been approved.
"""
from __future__ import annotations

import os
from typing import Mapping


PLATFORM_DEFINITIONS = (
    {
        "id": "youtube",
        "label": "YouTube",
        "detail": "Google 계정을 여러 개 연결하고 각 계정의 YouTube 채널을 관리할 수 있습니다.",
        "capabilities": ["account_connect", "channel_inventory", "private_upload", "analytics"],
        "adapter_ready": True,
    },
    {
        "id": "tiktok",
        "label": "TikTok",
        "detail": "TikTok 계정 인증과 Content Posting API 권한·앱 검증을 준비하고 있습니다.",
        "capabilities": ["account_connect", "video_publish"],
        "adapter_ready": False,
    },
    {
        "id": "instagram",
        "label": "Instagram",
        "detail": "Meta 계정 권한과 Instagram Reels 게시 API 검증을 준비하고 있습니다.",
        "capabilities": ["account_connect", "reels_publish", "insights"],
        "adapter_ready": False,
    },
    {
        "id": "facebook",
        "label": "Facebook",
        "detail": "Meta 페이지 연결 및 Reels 게시 권한 검증을 준비하고 있습니다.",
        "capabilities": ["page_connect", "reels_publish", "insights"],
        "adapter_ready": False,
    },
    {
        "id": "linkedin",
        "label": "LinkedIn",
        "detail": "조직·개인 계정 권한과 게시 API 승인을 검증한 뒤 연결을 제공합니다.",
        "capabilities": ["account_connect", "video_publish", "analytics"],
        "adapter_ready": False,
    },
)


def get_social_platform_catalog(env: Mapping[str, str] | None = None) -> list[dict]:
    """Return public capability metadata without exposing provider credentials."""
    values = os.environ if env is None else env
    google_ready = all(
        values.get(key, "").strip()
        for key in (
            "NEXUS_GOOGLE_OAUTH_CLIENT_ID",
            "NEXUS_GOOGLE_OAUTH_CLIENT_SECRET",
            "NEXUS_GOOGLE_OAUTH_REDIRECT_URI",
            "NEXUS_HOSTED_APP_URL",
        )
    )
    result = []
    for definition in PLATFORM_DEFINITIONS:
        item = dict(definition)
        item["capabilities"] = list(definition["capabilities"])
        if not definition["adapter_ready"]:
            item["status"] = "coming_soon"
            item["connectable"] = False
        elif item["id"] == "youtube" and google_ready:
            item["status"] = "ready"
            item["connectable"] = True
        else:
            item["status"] = "setup_required"
            item["connectable"] = False
        item["multiple_accounts"] = True
        result.append(item)
    return result
