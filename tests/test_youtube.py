from src.youtube import parse_duration, parse_video_item


def test_parse_duration():
    assert parse_duration("PT58S") == 58
    assert parse_duration("PT1M30S") == 90
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("P1DT1S") == 86401
    assert parse_duration("") == 0
    assert parse_duration("이상한값") == 0


def test_parse_video_item():
    item = {
        "id": "abc123",
        "snippet": {
            "title": "테스트 영상",
            "publishedAt": "2026-07-01T00:00:00Z",
            "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg"}},
        },
        "statistics": {"viewCount": "1234", "likeCount": "56", "commentCount": "7"},
        "contentDetails": {"duration": "PT2M10S"},
    }
    v = parse_video_item(item)
    assert v["video_id"] == "abc123"
    assert v["views"] == 1234
    assert v["likes"] == 56
    assert v["comments"] == 7
    assert v["duration"] == 130
    assert v["thumbnail"].endswith("hqdefault.jpg")


def test_parse_video_item_missing_stats():
    item = {
        "id": "abc",
        "snippet": {"title": "t", "publishedAt": "2026-07-01T00:00:00Z", "thumbnails": {}},
        "contentDetails": {},
    }
    v = parse_video_item(item)
    assert v["views"] is None
    assert v["thumbnail"] is None
    assert v["duration"] == 0
