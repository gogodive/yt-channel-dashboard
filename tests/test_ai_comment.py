import json
from datetime import datetime, timezone

from src import ai_comment
from src.ai_comment import build_messages, hit_key, maybe_generate, pick_baseline

NOW = datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc)


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


def test_pick_baseline_excludes_hits():
    hits = [video("h1", 900)]
    videos = hits + [video(f"v{i}", 100 + i) for i in range(10)]
    baseline = pick_baseline(videos, hits, 4)
    assert len(baseline) == 4
    assert all(v["video_id"] != "h1" for v in baseline)


def test_maybe_generate_no_hits_returns_none(tmp_path):
    assert maybe_generate(account([]), [], {}, tmp_path, NOW) is None


def test_maybe_generate_uses_cache_when_hits_unchanged(tmp_path, monkeypatch):
    hits = [video("h1", 500)]
    cache = {"hit_key": hit_key(hits), "comment": "캐시된 코멘트"}
    (tmp_path / "ai_comment_gogodive.json").write_text(
        json.dumps(cache), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("히트가 안 바뀌었는데 API 호출됨")

    monkeypatch.setattr(ai_comment, "generate", boom)
    out = maybe_generate(account(hits), hits, {}, tmp_path, NOW)
    assert out == "캐시된 코멘트"


def test_maybe_generate_skips_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    hits = [video("h1", 500)]
    assert maybe_generate(account(hits), hits, {}, tmp_path, NOW) is None


def test_maybe_generate_calls_api_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(ai_comment, "generate", lambda *a, **k: "새 코멘트")
    hits = [video("h1", 500)]
    out = maybe_generate(account(hits), hits, {}, tmp_path, NOW)
    assert out == "새 코멘트"
    cached = json.loads((tmp_path / "ai_comment_gogodive.json").read_text())
    assert cached["comment"] == "새 코멘트"
    assert cached["hit_key"] == hit_key(hits)
