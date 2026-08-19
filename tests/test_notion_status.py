from datetime import datetime, timedelta, timezone

from src.notion_status import (MARKER, build_status_text, find_status_block_id,
                               update_hub_callout)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 19, 7, 21, tzinfo=KST)
URL = "https://gogodive.github.io/yt-channel-dashboard/"
CONFIG = {"notion_status": {"hub_page_id": "page123", "dashboard_url": URL}}


def account(generated_at="2026-08-17T07:19:00+09:00"):
    return {"handle": "gogodive",
            "_ai_comment": {"comment": "c", "generated_at": generated_at}}


def flat(parts):
    return "".join(p["text"]["content"] for p in parts)


def test_build_status_text_contains_both_dates_and_link():
    parts = build_status_text(NOW, "2026-08-17T07:19:00+09:00", URL)
    text = flat(parts)
    assert "2026-08-19 07:21 갱신" in text
    assert "2026-08-17 기준" in text
    assert parts[0]["annotations"]["bold"] is True
    assert parts[-1]["text"]["link"]["url"] == URL


def test_build_status_text_without_analysis_date():
    text = flat(build_status_text(NOW, None, URL))
    assert "2026-08-19 07:21 갱신" in text
    assert "기준" not in text


class FakeResp:
    def __init__(self, payload=None):
        self._p = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class FakeSession:
    """노션 API 흉내 — 호출 인자를 기록한다."""

    def __init__(self, blocks):
        self.blocks = blocks
        self.patched = []

    def get(self, url, **kw):
        return FakeResp({"results": self.blocks})

    def patch(self, url, **kw):
        self.patched.append((url, kw["json"]))
        return FakeResp()


def callout_block(bid, text):
    return {"id": bid, "type": "callout",
            "callout": {"rich_text": [{"plain_text": text}]}}


def test_find_status_block_id_picks_marked_callout():
    session = FakeSession([
        {"id": "b0", "type": "paragraph",
         "paragraph": {"rich_text": [{"plain_text": MARKER}]}},   # 콜아웃 아님 → 무시
        callout_block("b1", "다른 안내 콜아웃"),                    # 마커 없음 → 무시
        callout_block("b2", f"{MARKER} · 데이터 ... 갱신"),
    ])
    assert find_status_block_id(session, "tok", "page123") == "b2"


def test_find_status_block_id_returns_none_when_absent():
    session = FakeSession([callout_block("b1", "관계없는 콜아웃")])
    assert find_status_block_id(session, "tok", "page123") is None


def test_update_skips_without_token(monkeypatch):
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    assert update_hub_callout(CONFIG, [account()], NOW) is False


def test_update_skips_without_config(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    assert update_hub_callout({}, [account()], NOW) is False


def test_update_patches_marked_block(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "tok")
    session = FakeSession([callout_block("b2", f"{MARKER} · 이전 내용")])
    monkeypatch.setattr("src.notion_status.requests.Session", lambda: session)
    assert update_hub_callout(CONFIG, [account()], NOW) is True
    url, body = session.patched[0]
    assert url.endswith("/blocks/b2")
    assert "2026-08-17 기준" in flat(body["callout"]["rich_text"])


def test_update_survives_api_failure(monkeypatch):
    """노션이 죽어도 파이프라인 전체는 실패하지 않는다."""
    monkeypatch.setenv("NOTION_TOKEN", "tok")

    class Boom(FakeSession):
        def get(self, url, **kw):
            raise RuntimeError("notion down")

    monkeypatch.setattr("src.notion_status.requests.Session", lambda: Boom([]))
    assert update_hub_callout(CONFIG, [account()], NOW) is False


def test_marker_does_not_match_description_callout():
    """설명용 콜아웃이 상태 콜아웃으로 오인돼 덮어써지면 안 된다."""
    description = ("📺 유튜브 데일리 대시보드: https://gogodive.github.io/... "
                   "매일 오전 7시 자동 갱신 · 채널당 최근 200개 영상 · "
                   "🤖 AI 썸네일 분석: 히트 영상 목록이 바뀐 날 + 매주 월요일에...")
    assert MARKER not in description

    session = FakeSession([
        callout_block("desc", description),
        callout_block("status", f"{MARKER} · 데이터 ... 갱신"),
    ])
    assert find_status_block_id(session, "tok", "page123") == "status"
