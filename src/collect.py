"""채널별 수집 오케스트레이션.

채널 하나가 실패해도 나머지는 진행하고, 실패 채널은 기존 JSON 을 유지한다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

from src.merge import merge_videos

log = logging.getLogger(__name__)


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_previous(data_dir: Path, handle: str) -> dict:
    p = data_dir / f"{handle}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"handle": handle, "subscribers": None, "fetched_at": None, "videos": []}


def _collect_channel(client, brand: dict, prev: dict, config: dict, now: datetime) -> dict:
    limit = config.get("display_limit", 120)
    freeze_days = config.get("freeze_days", 30)
    handle = brand["handle"]

    meta = client.resolve_channel(handle)
    ids = client.get_recent_video_ids(meta["uploads_playlist_id"], limit)
    fresh = client.get_videos_details(ids)

    # 쇼츠/롱폼 판별은 새 영상에 대해서만 1회 수행 (저장분은 merge 에서 유지)
    known_format = {v["video_id"]: v.get("format") for v in prev.get("videos", [])}
    for f in fresh:
        if not known_format.get(f["video_id"]):
            f["format"] = "shorts" if client.is_short(f["video_id"], f["duration"]) else "long"

    videos = merge_videos(prev.get("videos", []), fresh, now,
                          freeze_days=freeze_days, limit=limit)
    return {
        "brand": brand["name"],
        "handle": handle,
        "channel_title": meta["title"],
        "subscribers": meta["subscribers"],
        "fetched_at": now.isoformat(),
        "videos": videos,
    }


def collect_all(client, config: dict, data_dir: Path, now: datetime) -> list[dict]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for brand in config["channels"]:
        handle = brand["handle"]
        prev = _load_previous(data_dir, handle)
        prev.setdefault("brand", brand["name"])
        try:
            result = _collect_channel(client, brand, prev, config, now)
            (data_dir / f"{handle}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(result)
        except Exception:
            log.exception("%s 수집 실패 — 이전 데이터 유지", handle)
            results.append(prev)
    return results
