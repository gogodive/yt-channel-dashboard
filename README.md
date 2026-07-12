# 자사 유튜브 데일리 대시보드

자사 유튜브 채널(config.yaml 등록)의 영상을 매일 아침 7시(KST)에 수집해
썸네일 + 성과 지표 HTML 대시보드로 GitHub Pages 에 배포합니다.
인스타그램 대시보드(ig-feed-dashboard)와 같은 구조입니다.

- 채널당 최근 **120개** 영상 표시, 롱폼/쇼츠 구분
- 성과(조회·좋아요·댓글)는 **게시 후 30일까지만** 매일 갱신, 이후 동결(`확정` 배지)
- 🔥 히트 기준: 조회수가 **같은 채널·같은 포맷(롱폼/쇼츠) 중앙값의 2배 이상**, 3배 이상은 배수 표기
- 🤖 **AI 썸네일 분석**: 히트 영상 목록이 바뀐 날에만 Claude(비전)가 히트 vs 평균 썸네일을
  비교 분석한 코멘트를 생성 (변화 없으면 API 호출 없이 캐시 재사용)

## 일회성 셋업

### 1. YouTube Data API 키
1. https://console.cloud.google.com → 프로젝트 생성(또는 기존 사용)
2. API 및 서비스 → 라이브러리 → `YouTube Data API v3` 사용 설정
3. 사용자 인증 정보 → API 키 생성 → (권장) YouTube Data API v3 만 허용하도록 제한
4. 하루 무료 할당량 10,000 유닛 — 채널 1개 일일 수집은 수십 유닛 수준

### 2. Anthropic API 키 (AI 썸네일 코멘트용, 선택)
1. https://console.anthropic.com → API Keys → 키 생성
2. 없으면 AI 코멘트만 건너뛰고 대시보드는 정상 동작

### 3. GitHub
1. 이 저장소를 GitHub 에 push (public — Pages 무료 사용 조건)
2. Settings → Secrets and variables → Actions → `YOUTUBE_API_KEY`, `ANTHROPIC_API_KEY` 등록
3. Settings → Pages → Source: **GitHub Actions** 선택
4. Actions 탭 → daily-feed → **Run workflow** 로 첫 실행
5. 배포 URL 확인 → 노션에 링크 등록

## 로컬 실행 (검증용)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export YOUTUBE_API_KEY="..."
export ANTHROPIC_API_KEY="..."   # 선택
python -m src.main
open site/index.html
```

## 테스트

```bash
pytest -v
```

## 트러블슈팅
- **채널이 안 잡힘** — config.yaml 의 handle 이 유튜브 핸들(@뒤 부분)과 일치하는지 확인
- **쇼츠/롱폼이 잘못 분류됨** — data/<handle>.json 에서 해당 영상의 `format` 값을 수정하면 유지됨
- **AI 코멘트가 안 나옴** — `ANTHROPIC_API_KEY` 시크릿 등록 여부 확인, 히트 영상이 없으면 생성 안 함
- **실행 실패 메일** — GitHub 이 workflow 실패 시 자동 발송. Actions 탭에서 로그 확인
