"""엔트리포인트: 수집 → data/*.json 갱신 → AI 썸네일 코멘트 → site/index.html 생성."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ai_comment import maybe_generate
from src.collect import collect_all, load_config
from src.render import annotate_hot, render_html
from src.youtube import YouTubeClient

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YOUTUBE_API_KEY 환경변수가 없습니다", file=sys.stderr)
        return 1

    config = load_config(ROOT / "config.yaml")
    client = YouTubeClient(api_key)
    now = datetime.now(KST)
    data_dir = ROOT / "data"

    accounts = collect_all(client, config, data_dir, now)

    for acc in accounts:
        hits = annotate_hot(acc.get("videos", []))
        acc["_ai_comment"] = maybe_generate(acc, hits, config, data_dir, now)

    site = ROOT / "site"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(render_html(accounts, now), encoding="utf-8")
    print(f"완료: {len(accounts)}개 채널 → site/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
