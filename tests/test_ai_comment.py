import json
from datetime import datetime, timedelta, timezone

from src import ai_comment
from src.ai_comment import (build_messages, hit_key, is_weekly_refresh_due,
                            maybe_generate, pick_baseline)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 12, 7, 0, 0, tzinfo=KST)       # 일요일
MONDAY = datetime(2026, 7, 13, 7, 0, 0, tzinfo=KST)    # 월요일


def video(vid, views, ratio=None):
    v = {
        "video_id": vid,
        "title": f"영상 {vid}",
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "format": "long",
        "metrics": {"views": views},
    }
    if ratio:
        v["_ratio"] = ratio
    return v


def account(videos):
    return {"brand": "고고다이브", "handle": "gogodive", "videos": videos}


def write_cache(tmp_path, hits, comment="캐시된 코멘트", generated_at=None, hit_ids=True):
    cache = {"hit_key": hit_key(hits), "comment": comment,
             "generated_at": (generated_at or NOW).isoformat()}
    if hit_ids:
        cache["hit_ids"] = sorted(v["video_id"] for v in hits)
    (tmp_path / "ai_comment_gogodive.json").write_text(
        json.dumps(cache), encoding="utf-8")


def test_hit_key_order_independent():
    a = [video("a", 1), video("b", 2)]
    b = [video("b", 2), video("a", 1)]
    assert hit_key(a) == hit_key(b)


def test_build_messages_includes_images_and_stats():
    msgs = build_messages("고고다이브", [video("h1", 500, ratio=2.5)], [video("b1", 100)])
    content = msgs[0]["content"]
    images = [c for c in content if c["type"] == "image"]
    texts = " ".join(c["text"] for c in content if c["type"] == "text")
    assert len(images) == 2
    assert "2.5배" in texts
    assert "500" in texts
    assert "신규 진입" not in texts


def test_build_messages_marks_new_hits():
    msgs = build_messages("고고다이브", [video("h1", 500), video("h2", 400)],
                          [], new_ids={"h2"})
    texts = [c["text"] for c in msgs[0]["content"] if c["type"] == "text"]
    assert any("히트 1]" in t and "신규 진입" not in t for t in texts)
    assert any("히트 2 (신규 진입)]" in t for t in texts)


def test_pick_baseline_excludes_hits():
    hits = [video("h1", 900)]
    videos = hits + [video(f"v{i}", 100 + i) for i in range(10)]
    baseline = pick_baseline(videos, hits, 4)
    assert len(baseline) == 4
    assert all(v["video_id"] != "h1" for v in baseline)


def test_weekly_refresh_due_only_on_monday():
    cached = {"generated_at": NOW.isoformat()}
    assert is_weekly_refresh_due(cached, NOW) is False            # 일요일
    assert is_weekly_refresh_due(cached, MONDAY) is True          # 월요일, 캐시는 일요일 것
    fresh = {"generated_at": MONDAY.isoformat()}
    assert is_weekly_refresh_due(fresh, MONDAY) is False          # 월요일에 이미 생성됨
    assert is_weekly_refresh_due(None, MONDAY) is True


def test_maybe_generate_no_hits_returns_none(tmp_path):
    assert maybe_generate(account([]), [], {}, tmp_path, NOW) is None


def test_maybe_generate_uses_cache_when_hits_unchanged(tmp_path, monkeypatch):
    hits = [video("h1", 500)]
    write_cache(tmp_path, hits)

    def boom(*a, **k):
        raise AssertionError("히트가 안 바뀌었는데 API 호출됨")

    monkeypatch.setattr(ai_comment, "generate", boom)
    out = maybe_generate(account(hits), hits, {}, tmp_path, NOW)
    assert out["comment"] == "캐시된 코멘트"
    assert out["generated_at"] == NOW.isoformat()


def test_maybe_generate_monday_forces_regen(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    hits = [video("h1", 500)]
    write_cache(tmp_path, hits, generated_at=NOW)  # 일요일에 만든 캐시, 히트 동일
    monkeypatch.setattr(ai_comment, "generate", lambda *a, **k: "월요일 재분석")
    out = maybe_generate(account(hits), hits, {}, tmp_path, MONDAY)
    assert out["comment"] == "월요일 재분석"
    assert out["generated_at"] == MONDAY.isoformat()


def test_maybe_generate_passes_new_hit_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    old_hits = [video("h1", 500)]
    write_cache(tmp_path, old_hits)
    captured = {}

    def fake_generate(brand, hits, baseline, model, new_ids=frozenset()):
        captured["new_ids"] = set(new_ids)
        return "새 코멘트"

    monkeypatch.setattr(ai_comment, "generate", fake_generate)
    new_hits = [video("h1", 500), video("h2", 700)]
    out = maybe_generate(account(new_hits), new_hits, {}, tmp_path, NOW)
    assert out["comment"] == "새 코멘트"
    assert captured["new_ids"] == {"h2"}


def test_maybe_generate_skips_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    hits = [video("h1", 500)]
    assert maybe_generate(account(hits), hits, {}, tmp_path, NOW) is None


def test_maybe_generate_calls_api_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_comment, "generate", lambda *a, **k: "새 코멘트")
    hits = [video("h1", 500)]
    out = maybe_generate(account(hits), hits, {}, tmp_path, NOW)
    assert out["comment"] == "새 코멘트"
    cached = json.loads((tmp_path / "ai_comment_gogodive.json").read_text())
    assert cached["comment"] == "새 코멘트"
    assert cached["hit_key"] == hit_key(hits)
    assert cached["hit_ids"] == ["h1"]
