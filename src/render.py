"""수집 결과 → 단일 HTML 대시보드."""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape, Undefined

KST = timezone(timedelta(hours=9))
_TEMPLATE_DIR = Path(__file__).parent

HOT_RATIO = 2.0          # 같은 포맷(쇼츠/롱폼) 중앙값 대비 이 배수 이상이면 🔥
HOT_RATIO_LABELED = 3.0  # 이 배수 이상이면 배수까지 표기 (🔥 4.2x)
HOT_MIN_VIDEOS = 5       # 포맷별 조회수 있는 영상이 이보다 적으면 표시 안 함
CHART_DAYS = 730         # 조회수 추이 차트 표시 기간 (최근 2년)


def _fmt_num(v) -> str:
    if v is None or isinstance(v, Undefined):
        return "–"
    return f"{v:,}"


def _fmt_dur(seconds) -> str:
    if not seconds:
        return ""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt_date(ts: str) -> str:
    if not ts:
        return ""
    return _parse_ts(ts).astimezone(KST).strftime("%Y-%m-%d")


def _days_since(published_at: str, generated_at: datetime) -> int:
    return (generated_at - _parse_ts(published_at)).days


def annotate_hot(videos: list[dict]) -> list[dict]:
    """포맷(쇼츠/롱폼)별 조회수 중앙값 대비 배수로 히트 영상에 _hot 라벨을 단다.

    히트 영상 리스트를 반환한다 (AI 썸네일 코멘트 입력용).
    """
    hits: list[dict] = []
    for fmt in ("long", "shorts"):
        group = [v for v in videos if v.get("format") == fmt]
        views = [v["metrics"].get("views") for v in group]
        views = [x for x in views if isinstance(x, int) and x > 0]
        if len(views) < HOT_MIN_VIDEOS:
            continue
        median = statistics.median(views)
        if median <= 0:
            continue
        for v in group:
            x = v["metrics"].get("views")
            if isinstance(x, int) and x / median >= HOT_RATIO:
                ratio = x / median
                v["_ratio"] = ratio
                v["_hot"] = f"🔥 {ratio:.1f}x" if ratio >= HOT_RATIO_LABELED else "🔥"
                hits.append(v)
    hits.sort(key=lambda v: v.get("_ratio", 0), reverse=True)
    return hits


def chart_points(videos: list[dict], generated_at: datetime,
                 days: int = CHART_DAYS) -> list[dict]:
    """조회수 추이 산점도용 데이터 (최근 days일, 조회수 있는 영상만)."""
    cutoff = generated_at - timedelta(days=days)
    pts = []
    for v in videos:
        views = v["metrics"].get("views")
        if not isinstance(views, int) or views <= 0:
            continue
        if _parse_ts(v["published_at"]) < cutoff:
            continue
        pts.append({"t": v.get("title", ""), "d": v["published_at"][:10],
                    "v": views, "f": v.get("format"), "h": bool(v.get("_hot"))})
    pts.sort(key=lambda p: p["d"])
    return pts


def render_html(accounts: list[dict], generated_at: datetime) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["num"] = _fmt_num
    env.filters["date"] = _fmt_date
    env.filters["dur"] = _fmt_dur
    tpl = env.get_template("template.html")
    gen_date = generated_at.astimezone(KST).date()
    for acc in accounts:
        fetched = acc.get("fetched_at")
        acc["_stale_date"] = None
        if fetched:
            fdt = _parse_ts(fetched).astimezone(KST)
            if fdt.date() != gen_date:
                acc["_stale_date"] = fdt.strftime("%Y-%m-%d")
        videos = acc.get("videos", [])
        for v in videos:
            v["_days"] = _days_since(v["published_at"], generated_at)
        annotate_hot(videos)
        acc["_long"] = [v for v in videos if v.get("format") != "shorts"]
        acc["_shorts"] = [v for v in videos if v.get("format") == "shorts"]
        acc["_chart"] = chart_points(videos, generated_at)
    return tpl.render(
        accounts=accounts,
        generated_label=generated_at.astimezone(KST).strftime("%Y-%m-%d %H:%M"),
    )
