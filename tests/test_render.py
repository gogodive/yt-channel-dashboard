from datetime import datetime, timezone

from src.render import annotate_hot, chart_points, render_html

NOW = datetime(2026, 7, 12, 7, 0, 0, tzinfo=timezone.utc)


def video(vid, views, fmt="long", ts="2026-07-01T00:00:00Z"):
    return {
        "video_id": vid,
        "title": f"영상 {vid}",
        "url": f"https://www.youtube.com/watch?v={vid}",
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "published_at": ts,
        "duration": 60 if fmt == "shorts" else 600,
        "format": fmt,
        "frozen": False,
        "metrics": {"views": views, "likes": 1, "comments": 1},
        "metrics_updated_at": NOW.isoformat(),
    }


def test_annotate_hot_per_format():
    # 롱폼 중앙값 100 → v_hot(250)은 2.5배 히트, 쇼츠는 5개 미만이라 판정 없음
    videos = [video(f"L{i}", 100) for i in range(5)] + [video("v_hot", 250)]
    videos += [video("S1", 100000, fmt="shorts")]
    hits = annotate_hot(videos)
    assert [v["video_id"] for v in hits] == ["v_hot"]
    assert videos[-2]["_hot"] == "🔥"
    assert "_hot" not in videos[-1]


def test_annotate_hot_ratio_label():
    videos = [video(f"L{i}", 100) for i in range(5)] + [video("big", 420)]
    annotate_hot(videos)
    assert videos[-1]["_hot"] == "🔥 4.2x"


def test_annotate_hot_too_few_videos():
    videos = [video("L1", 100), video("L2", 999)]
    assert annotate_hot(videos) == []


def test_render_html_smoke():
    account = {
        "brand": "고고다이브",
        "handle": "gogodive",
        "channel_title": "고고다이브",
        "subscribers": 12345,
        "fetched_at": NOW.isoformat(),
        "videos": [video(f"L{i}", 100) for i in range(5)]
        + [video("hot1", 300), video("S1", 50, fmt="shorts")],
        "_ai_comment": {"comment": "[히트 썸네일 공통 패턴] 테스트 코멘트",
                        "generated_at": "2026-07-12T07:00:00+09:00"},
    }
    html = render_html([account], NOW)
    assert "고고다이브" in html
    assert "구독자 12,345" in html
    assert "🔥 3.0x" in html
    assert "AI 썸네일 분석" in html
    assert "테스트 코멘트" in html
    assert "분석 기준일 2026-07-12" in html
    assert "쇼츠" in html and "롱폼" in html


def test_chart_points_filters_and_sorts():
    videos = [
        video("recent", 500, ts="2026-07-01T00:00:00Z"),
        video("old", 900, ts="2023-01-01T00:00:00Z"),      # 2년 밖 → 제외
        video("early", 300, ts="2026-01-01T00:00:00Z"),
    ]
    videos.append({**video("noviews", 0, ts="2026-06-01T00:00:00Z"),
                   "metrics": {"views": None}})            # 조회수 없음 → 제외
    pts = chart_points(videos, NOW)
    assert [p["d"] for p in pts] == ["2026-01-01", "2026-07-01"]
    assert pts[0]["v"] == 300 and pts[0]["f"] == "long"


def test_chart_points_marks_hot():
    videos = [video(f"L{i}", 100) for i in range(5)] + [video("hot", 300)]
    annotate_hot(videos)
    pts = chart_points(videos, NOW)
    assert [p["h"] for p in pts].count(True) == 1


def test_render_html_includes_chart():
    account = {
        "brand": "고고다이브", "handle": "gogodive",
        "subscribers": 1, "fetched_at": NOW.isoformat(),
        "videos": [video(f"L{i}", 100) for i in range(5)],
    }
    html = render_html([account], NOW)
    assert "조회수 추이 (최근 2년)" in html
    assert 'id="chart-data-0"' in html
    assert "선형 축" in html and "로그 축" in html


def test_render_html_stale_banner():
    account = {
        "brand": "고고다이브", "handle": "gogodive",
        "subscribers": None,
        "fetched_at": "2026-07-01T07:00:00+09:00",
        "videos": [],
    }
    html = render_html([account], NOW)
    assert "최근 수집 실패" in html
