"""히트 영상 썸네일 패턴 AI 분석 (Claude 비전).

재분석 시점: 히트 영상 목록이 바뀐 날 + 매주 월요일(무조건 1회).
그 외에는 캐시를 재사용한다. 신규 진입 히트작은 프롬프트에 표시해
코멘트에서 따로 짚어준다.
ANTHROPIC_API_KEY 가 없으면 캐시(있으면)만 반환하고 조용히 건너뛴다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """당신은 유튜브 썸네일 전문 분석가입니다. 한 채널의 '히트 영상'(같은 채널 평소 조회수 중앙값의 2배 이상) 썸네일과 비교용 '평균 성과' 썸네일을 보고, 무엇이 클릭을 끌어냈는지 분석합니다.

다음 형식으로 한국어로 답하세요. 마크다운 헤더 없이 아래 단락 구조를 지키되, 각 단락은 3~5문장으로 간결하게:

[히트 썸네일 공통 패턴] 텍스트 유무·크기·문구 톤, 인물/피사체, 색감·대비, 구도 등 눈에 보이는 공통점.
[평균 성과 대비 차이] 히트작과 평균작 썸네일의 결정적 차이.
[다음 썸네일 제안] 이 채널이 바로 적용할 수 있는 구체적 제안 2~3가지.

라벨에 (신규 진입)이 붙은 히트작이 하나라도 있으면, 맨 앞에 [이번에 새로 진입한 히트작] 단락을 추가해 그 영상(들)의 썸네일이 어떤 점에서 통했는지 먼저 짚어주세요. 신규 진입이 없으면 이 단락은 생략합니다.

썸네일에 실제로 보이는 것만 근거로 삼고, 추측은 추측이라고 표시하세요."""


def _cache_path(data_dir: Path, handle: str) -> Path:
    return Path(data_dir) / f"ai_comment_{handle}.json"


def hit_key(hits: list[dict]) -> str:
    ids = sorted(v["video_id"] for v in hits)
    return hashlib.sha256(",".join(ids).encode()).hexdigest()


def load_cache(data_dir: Path, handle: str) -> dict | None:
    p = _cache_path(data_dir, handle)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _result(cached: dict | None) -> dict | None:
    if cached and cached.get("comment"):
        return {"comment": cached["comment"], "generated_at": cached.get("generated_at")}
    return None


def is_weekly_refresh_due(cached: dict | None, now: datetime) -> bool:
    """월요일이고, 캐시가 오늘 만든 것이 아니면 강제 재분석."""
    if now.weekday() != 0:
        return False
    if not cached or not cached.get("generated_at"):
        return True
    gen = datetime.fromisoformat(cached["generated_at"])
    return gen.astimezone(now.tzinfo).date() != now.date()


def _video_line(v: dict, label: str) -> str:
    views = v["metrics"].get("views")
    ratio = v.get("_ratio")
    ratio_s = f", 중앙값 대비 {ratio:.1f}배" if ratio else ""
    fmt = "쇼츠" if v.get("format") == "shorts" else "롱폼"
    return f"[{label}] ({fmt}) \"{v['title']}\" — 조회수 {views:,}{ratio_s}" if views else \
        f"[{label}] ({fmt}) \"{v['title']}\""


def build_messages(brand: str, hits: list[dict], baseline: list[dict],
                   new_ids: set[str] = frozenset()) -> list[dict]:
    content: list[dict] = [{
        "type": "text",
        "text": f"채널: {brand}\n아래 순서대로 히트 썸네일 {len(hits)}개, "
                f"비교용 평균 성과 썸네일 {len(baseline)}개입니다.",
    }]
    for i, v in enumerate(hits, 1):
        label = f"히트 {i} (신규 진입)" if v["video_id"] in new_ids else f"히트 {i}"
        content.append({"type": "text", "text": _video_line(v, label)})
        content.append({"type": "image", "source": {"type": "url", "url": v["thumbnail"]}})
    for i, v in enumerate(baseline, 1):
        content.append({"type": "text", "text": _video_line(v, f"평균 {i}")})
        content.append({"type": "image", "source": {"type": "url", "url": v["thumbnail"]}})
    return [{"role": "user", "content": content}]


def pick_baseline(videos: list[dict], hits: list[dict], max_baseline: int) -> list[dict]:
    """히트가 아니면서 조회수가 중간 수준인 영상을 비교군으로 고른다."""
    hit_ids = {v["video_id"] for v in hits}
    rest = [v for v in videos
            if v["video_id"] not in hit_ids
            and v.get("thumbnail")
            and isinstance(v["metrics"].get("views"), int)]
    rest.sort(key=lambda v: v["metrics"]["views"], reverse=True)
    mid = len(rest) // 2
    half = max_baseline // 2
    return rest[max(0, mid - half):mid + (max_baseline - half)]


def generate(brand: str, hits: list[dict], baseline: list[dict], model: str,
             new_ids: set[str] = frozenset()) -> str:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=build_messages(brand, hits, baseline, new_ids),
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()


def maybe_generate(account: dict, hits: list[dict], config: dict,
                   data_dir: Path, now: datetime) -> dict | None:
    """히트 목록 변경 시 + 매주 월요일에 생성.

    반환값: {"comment", "generated_at"} 또는 None.
    """
    ai_cfg = config.get("ai_comment", {})
    handle = account["handle"]
    hits = [v for v in hits if v.get("thumbnail")][: ai_cfg.get("max_hits", 10)]
    cached = load_cache(data_dir, handle)

    if not hits:
        return None
    key = hit_key(hits)
    hits_changed = not cached or cached.get("hit_key") != key
    if not hits_changed and not is_weekly_refresh_due(cached, now):
        return _result(cached)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("%s: ANTHROPIC_API_KEY 없음 — AI 썸네일 코멘트 건너뜀", handle)
        return _result(cached)

    prev_ids = set((cached or {}).get("hit_ids") or [])
    new_ids = {v["video_id"] for v in hits} - prev_ids if prev_ids else set()

    baseline = pick_baseline(account.get("videos", []), hits,
                             ai_cfg.get("max_baseline", 6))
    try:
        comment = generate(account["brand"], hits, baseline,
                           ai_cfg.get("model", DEFAULT_MODEL), new_ids)
    except Exception:
        log.exception("%s: AI 썸네일 코멘트 생성 실패 — 이전 코멘트 유지", handle)
        return _result(cached)

    cache = {"hit_key": key, "hit_ids": sorted(v["video_id"] for v in hits),
             "comment": comment, "generated_at": now.isoformat()}
    _cache_path(data_dir, handle).write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return _result(cache)
