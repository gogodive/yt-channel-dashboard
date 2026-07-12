"""YouTube Data API v3 클라이언트 (API 키, requests 기반) + 쇼츠 판별."""

from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
SHORTS_MAX_SECONDS = 183  # 이 길이를 넘으면 쇼츠일 수 없음 (URL 확인 생략)

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_duration(iso: str) -> int:
    """ISO 8601 길이 문자열(PT1M30S 등) → 초. 파싱 실패 시 0."""
    m = _DURATION_RE.match(iso or "")
    if not m:
        return 0
    parts = {k: int(v) for k, v in m.groupdict().items() if v}
    return (parts.get("days", 0) * 86400 + parts.get("hours", 0) * 3600
            + parts.get("minutes", 0) * 60 + parts.get("seconds", 0))


def parse_video_item(item: dict) -> dict:
    """videos.list 응답 아이템 → 표준 형태."""
    sn = item["snippet"]
    st = item.get("statistics", {})
    cd = item.get("contentDetails", {})
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    return {
        "video_id": item["id"],
        "title": sn.get("title", ""),
        "published_at": sn.get("publishedAt"),
        "duration": parse_duration(cd.get("duration", "")),
        "thumbnail": thumb,
        "views": int(st["viewCount"]) if "viewCount" in st else None,
        "likes": int(st["likeCount"]) if "likeCount" in st else None,
        "comments": int(st["commentCount"]) if "commentCount" in st else None,
    }


class YouTubeClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, path: str, **params) -> dict:
        params["key"] = self.api_key
        r = self.session.get(f"{API_BASE}/{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def resolve_channel(self, handle: str) -> dict:
        """핸들(@ 없이) → 채널 메타(제목/구독자/업로드 재생목록 ID)."""
        resp = self._get("channels", part="snippet,statistics,contentDetails",
                         forHandle=handle.lstrip("@"))
        items = resp.get("items", [])
        if not items:
            raise LookupError(f"채널을 찾을 수 없음: @{handle}")
        it = items[0]
        stats = it.get("statistics", {})
        return {
            "channel_id": it["id"],
            "title": it["snippet"]["title"],
            "subscribers": None if stats.get("hiddenSubscriberCount")
            else int(stats.get("subscriberCount", 0)),
            "uploads_playlist_id": it["contentDetails"]["relatedPlaylists"]["uploads"],
        }

    def get_recent_video_ids(self, uploads_playlist_id: str, limit: int) -> list[str]:
        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            params = {"part": "contentDetails", "playlistId": uploads_playlist_id,
                      "maxResults": min(50, limit - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            resp = self._get("playlistItems", **params)
            for it in resp.get("items", []):
                ids.append(it["contentDetails"]["videoId"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids[:limit]

    def get_videos_details(self, video_ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            resp = self._get("videos", part="snippet,statistics,contentDetails",
                             id=",".join(batch))
            out.extend(parse_video_item(it) for it in resp.get("items", []))
        return out

    def is_short(self, video_id: str, duration: int) -> bool:
        """쇼츠 여부. /shorts/{id} 가 200이면 쇼츠, 리다이렉트면 롱폼.

        3분 초과 영상은 쇼츠일 수 없어 요청을 생략한다.
        확인 실패 시 60초 이하만 쇼츠로 추정.
        """
        if duration > SHORTS_MAX_SECONDS:
            return False
        try:
            r = self.session.head(f"https://www.youtube.com/shorts/{video_id}",
                                  allow_redirects=False, timeout=10)
            if r.status_code == 200:
                return True
            if 300 <= r.status_code < 400:
                return False
        except requests.RequestException:
            log.warning("쇼츠 판별 실패: %s — 길이로 추정", video_id)
        return duration <= 60
