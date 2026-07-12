from datetime import datetime, timezone

from src.merge import is_frozen, merge_videos

NOW = datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc)


def video(vid, ts, **kw):
    base = {
        "video_id": vid,
        "title": "제목",
        "published_at": ts,
        "duration": 300,
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "format": "long",
        "views": 100,
        "likes": 10,
        "comments": 1,
    }
    base.update(kw)
    return base


def test_is_frozen_boundary():
    assert is_frozen("2026-06-01T00:00:00Z", NOW) is True   # 41일 전
    assert is_frozen("2026-07-01T00:00:00Z", NOW) is False  # 11일 전


def test_recent_video_gets_fresh_metrics():
    out = merge_videos([], [video("v1", "2026-07-01T00:00:00Z", views=123)], NOW)
    assert out[0]["metrics"]["views"] == 123
    assert out[0]["frozen"] is False
    assert out[0]["metrics_updated_at"] is not None


def test_old_video_keeps_stored_metrics_frozen():
    stored = [{
        "video_id": "v1",
        "format": "long",
        "metrics": {"views": 999, "likes": 9, "comments": 9},
        "metrics_updated_at": "2026-06-01T07:00:00+09:00",
    }]
    fresh = [video("v1", "2026-05-01T00:00:00Z", views=555)]
    out = merge_videos(stored, fresh, NOW)
    assert out[0]["frozen"] is True
    assert out[0]["metrics"]["views"] == 999  # 동결값 유지
    assert out[0]["metrics_updated_at"] == "2026-06-01T07:00:00+09:00"


def test_old_video_without_stored_metrics_backfills():
    fresh = [video("v1", "2026-05-01T00:00:00Z", views=555)]
    out = merge_videos([], fresh, NOW)
    assert out[0]["frozen"] is True
    assert out[0]["metrics"]["views"] == 555  # 최초 1회 백필


def test_stored_format_wins_over_fresh():
    stored = [{"video_id": "v1", "format": "shorts", "metrics": {"views": 1}}]
    fresh = [video("v1", "2026-07-01T00:00:00Z", format="long")]
    out = merge_videos(stored, fresh, NOW)
    assert out[0]["format"] == "shorts"


def test_missing_fresh_video_is_dropped():
    stored = [{"video_id": "gone", "format": "long", "metrics": {"views": 1}}]
    out = merge_videos(stored, [video("v1", "2026-07-01T00:00:00Z")], NOW)
    assert [v["video_id"] for v in out] == ["v1"]


def test_limit_applies():
    fresh = [video(f"v{i}", "2026-07-01T00:00:00Z") for i in range(10)]
    out = merge_videos([], fresh, NOW, limit=3)
    assert len(out) == 3
