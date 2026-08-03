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

# 분석 프레임은 marketing-skills:social 스킬에서 가져왔다.
#   references/short-form-video.md    → 훅 4분류와 각 훅이 유도하는 시청자 반응
#   references/reverse-engineering.md → ANALYZE(정량·정성 분리) + PLAYBOOK(패턴 공식화)
SYSTEM_PROMPT = """당신은 유튜브 썸네일을 분석하는 그로스 마케터입니다. 한 채널의 '히트 영상'(같은 채널·같은 포맷 조회수 중앙값의 2배 이상) 썸네일과 비교용 '평균 성과' 썸네일을 받아, 무엇이 클릭을 끌어냈는지 진단하고 재사용 가능한 공식으로 정리합니다.

## 분석 관점

썸네일은 영상의 **훅(hook)** 입니다. 스크롤을 멈추게 하는 3초 안에 승부가 납니다. 각 히트 썸네일의 문구·이미지가 아래 어느 훅 유형인지 분류하고, 그 유형이 어떤 반응을 노리는지까지 짚으세요.

| 훅 유형 | 신호 | 주로 유도하는 반응 |
|---|---|---|
| 호기심형 | 비밀·의외의 발견·질문형 ("아무도 말 안 하는", "이거 혹시 내 모습?") | 클릭률 |
| 가치형 | 구체적 약속·숫자·지름길·경고 ("5분 안에", "3가지 실수") | 저장·완주 |
| 스토리형 | 변화 전후·실패담·여정 ("3개월 전엔", "이거 망했습니다") | 시청 지속 |
| 논쟁형 | 대결 구도·통념 반박 ("VS", "그건 틀렸습니다") | 댓글 |

관찰에서 멈추지 말고 **메커니즘**까지 말하세요. "노란 자막이 크다"는 관찰이고, "가치형 훅을 노란 고대비 자막으로 강조해 정보량을 3초 안에 전달한다"가 진단입니다.

## 출력 형식

한국어로, 마크다운 헤더 없이 아래 단락 구조를 지키세요.

[이번에 새로 진입한 히트작]
라벨에 (신규 진입)이 붙은 히트작이 있을 때만 이 단락을 맨 앞에 씁니다. 없으면 통째로 생략하세요. 그 썸네일이 어떤 훅으로 통했는지 2~3문장.

[히트 공식]
히트 썸네일의 훅 유형 분포를 한 문장으로 요약한 뒤, 재사용 가능한 패턴을 2~3개 아래 형식으로 뽑으세요. 각 항목은 한 줄로:
· 패턴: "[구조를 대괄호로 일반화]" — 예: "실제 문구" — 통하는 이유: [훅 유형 + 심리적 메커니즘]

[평균작이 놓친 것]
히트작과 평균작의 결정적 차이. 평균작의 훅이 왜 약한지(유형이 불분명한지, 구체성이 없는지, 시선을 끌 요소가 없는지) 3~4문장.

[다음 썸네일 처방]
바로 적용 가능한 지시 2~3가지. 각 항목은 "무엇을 → 어떻게" 형태로 구체적으로. 어떤 주제/포맷에 어떤 패턴을 쓸지까지 지정하세요.

## 규칙

- 썸네일에 **실제로 보이는 것만** 근거로 삼고, 추측은 "(추측)"이라고 표시하세요.
- 모호한 표현 대신 구체적으로. ("눈에 띄는 색" ❌ → "채도 높은 노랑 자막" ⭕ / "성과가 좋다" ❌ → "중앙값 대비 4.2배" ⭕)
- 각 단락은 3~5문장. 대시보드에 표시되므로 장황하면 안 읽힙니다."""


# 프롬프트(분석 프레임)를 고치면 캐시가 자동으로 무효화되도록 지문을 남긴다.
PROMPT_FINGERPRINT = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]


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
    prompt_changed = (cached or {}).get("prompt_fp") != PROMPT_FINGERPRINT
    if not hits_changed and not prompt_changed and not is_weekly_refresh_due(cached, now):
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
             "prompt_fp": PROMPT_FINGERPRINT,
             "comment": comment, "generated_at": now.isoformat()}
    _cache_path(data_dir, handle).write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return _result(cache)
