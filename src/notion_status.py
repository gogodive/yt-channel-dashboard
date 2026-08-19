"""노션 허브 페이지 최상단 콜아웃에 마지막 갱신 상태를 기록한다.

허브 페이지에서 `MARKER` 문구를 포함한 첫 콜아웃 블록을 찾아 그 내용만 갈아끼운다.
(블록 ID 를 하드코딩하지 않으므로 콜아웃을 지웠다 다시 만들어도 계속 동작한다.)

NOTION_TOKEN 이 없거나 호출이 실패해도 파이프라인 전체는 계속 진행한다 (best-effort).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import requests

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MARKER = "유튜브 대시보드"   # 이 문구가 든 콜아웃을 갱신 대상으로 삼는다


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json"}


def _plain_text(block: dict) -> str:
    rich = block.get(block.get("type", ""), {}).get("rich_text", [])
    return "".join(r.get("plain_text", "") for r in rich)


def build_status_text(generated_at: datetime, analyzed_at: str | None,
                      url: str, label: str = MARKER) -> list[dict]:
    """콜아웃에 넣을 Notion rich_text 페이로드 (순수 함수)."""
    parts: list[dict] = [
        {"type": "text", "text": {"content": label}, "annotations": {"bold": True}},
        {"type": "text",
         "text": {"content": f" · 데이터 {generated_at.strftime('%Y-%m-%d %H:%M')} 갱신"}},
    ]
    if analyzed_at:
        parts.append({"type": "text",
                      "text": {"content": f" · AI 썸네일 분석 {analyzed_at[:10]} 기준"}})
    parts.append({"type": "text", "text": {"content": " · "}})
    parts.append({"type": "text", "text": {"content": "열기", "link": {"url": url}}})
    return parts


def find_status_block_id(session, token: str, page_id: str) -> str | None:
    r = session.get(f"{API}/blocks/{page_id}/children",
                    headers=_headers(token), params={"page_size": 100}, timeout=30)
    r.raise_for_status()
    for block in r.json().get("results", []):
        if block.get("type") == "callout" and MARKER in _plain_text(block):
            return block["id"]
    return None


def update_hub_callout(config: dict, accounts: list[dict], now: datetime) -> bool:
    """허브 콜아웃을 갱신. 성공하면 True, 건너뛰거나 실패하면 False."""
    cfg = config.get("notion_status") or {}
    page_id = cfg.get("hub_page_id")
    if not page_id:
        return False
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log.warning("NOTION_TOKEN 없음 — 노션 허브 콜아웃 갱신 건너뜀")
        return False

    analyzed_at = next(
        (a["_ai_comment"]["generated_at"] for a in accounts
         if (a.get("_ai_comment") or {}).get("generated_at")), None)

    try:
        session = requests.Session()
        block_id = find_status_block_id(session, token, page_id)
        if not block_id:
            log.warning("허브 페이지에 '%s' 콜아웃이 없어 갱신 건너뜀", MARKER)
            return False
        r = session.patch(
            f"{API}/blocks/{block_id}",
            headers=_headers(token),
            json={"callout": {"rich_text": build_status_text(
                now, analyzed_at, cfg.get("dashboard_url", ""))}},
            timeout=30)
        r.raise_for_status()
        log.info("노션 허브 콜아웃 갱신 완료")
        return True
    except Exception:
        log.exception("노션 허브 콜아웃 갱신 실패 — 무시하고 계속 진행")
        return False
