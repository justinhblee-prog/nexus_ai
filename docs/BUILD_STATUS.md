# NEXUS STUDIO PRO — BUILD STATUS

기준일: 2026-11-27  
저장소: `justinhblee-prog/nexus_ai`

## 최신 Hosted SaaS 진행 현황

**IN PROGRESS · PR #11 Draft/Open**

- 작업 브랜치: `feat/nexus-user-onboarding-web-oauth-20261127`
- 최신 검증 커밋: `cd56a63ff8c85cf771c9c4684b01f3001123bcf8`
- Pull Request: [#11 — User onboarding and hosted OAuth](https://github.com/justinhblee-prog/nexus_ai/pull/11)
- 최신 CI: [run 46014117426](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46013800343) — **309 Python tests PASS**, Docker Compose 검증, Python 컴파일, 브라우저 JavaScript 구문, Playwright 브라우저 smoke 모두 통과.
- Vercel 새 Preview 배포는 무료 플랜 일일 배포 한도 때문에 대기 중. 이전 Preview는 현재 PR head를 반영하지 않으므로 최신 화면으로 간주하지 않음.
- Supabase 운영 프로젝트에는 이번 작업에서 DDL/마이그레이션을 적용하지 않음.

### 이번 트랙에서 완료된 코드

- Hosted root route, signup/login/password recovery, 사용자별 워크스페이스 화면 연결.
- Hosted overview 통계는 RLS 적용된 exact count 쿼리로 계산.
- Shorts 작업 내역은 50건 단위 페이지네이션, 안정 정렬, 워크스페이스 전환 stale-response 방지 적용.
- 최종 승인 API는 현재 상태 및 owner/admin 역할을 재검증하고 조건부 갱신.
- Vercel FastAPI entrypoint 분리. 로컬 Streamlit `app.py`는 보존하고 Hosted cold start에서는 로컬 영상/분석/업로드 모듈을 로드하지 않음.
- Hosted trend endpoint는 SQLite를 쓰기/초기화하지 않으며, 저장소 부재 상태를 UI에 명시.
- Saved topic queue의 사용자·워크스페이스 scoped list/add/delete API 및 화면 연동. 기존 브라우저 항목은 서버 테이블이 준비되면 자동 이전. 이 큐는 `shorts_jobs`와 분리되며 render/upload worker가 소비하지 않음.
- 큐 스키마/RLS/계정삭제 cascade 설계 및 CLI 생성 절차: [TOPIC_QUEUE_SERVER_PERSISTENCE.md](TOPIC_QUEUE_SERVER_PERSISTENCE.md)

### 현재 외부 의존 및 검증 차단 항목

1. **Topic queue DB migration** — 설계 SQL은 문서화했으나, 로컬 Supabase CLI/repository checkout이 이 세션에 없어 CLI가 생성한 timestamp migration 파일은 아직 없음. 마이그레이션 적용도 미실행. 로컬 checkout에서 `supabase migration new nexus_user_workspace_topic_queue`로 생성 후 검토해야 함.
2. **Hosted trend feed** — Vercel 번들에 공유 trend snapshot이 없으므로 현재는 unavailable 상태. 영속 공유 데이터 테이블 및 수집 파이프라인 필요.
3. **Google OAuth 실계정 E2E** — 사용자 동의, refresh/revoke, 실제 테스트 채널 검증 미완료.
4. **Two-user tenant isolation E2E** — 자동화된 계약 테스트는 있으나 서로 다른 실제 사용자 계정으로 검증 미완료.
5. **Vercel Preview runtime** — 새 Preview 배포 및 HTTP/browser 연결 확인은 배포 한도 해제 후 필요.
6. **Hosted secrets/configuration** — 현재 Preview scope에는 Supabase URL과 publishable key만 등록. Google OAuth, redirect URI, token encryption key, hosted app URL 등 민감 설정은 안전한 Vercel 환경 설정 절차가 필요하며 채팅에 비밀값을 입력하지 않음.

### 안전 경계

- PR #11은 Draft/Open 유지. merge/push-to-main/production deploy 금지.
- Supabase live migration/DDL 미적용. 서비스 프로젝트 `ai_studio` 및 dormant `ai_studio_test` 보존.
- YouTube 공개 업로드 및 자동 공개 전환 금지. 업로드는 명시적 승인 후 Private만 허용.
- 유료 API, 유료 인프라, 플랜 업그레이드 사용 금지.
- 계정 삭제와 공유 워크스페이스 데이터 보존은 완료 조건에서 제외하지 않음.

---

## 로컬 데스크톱 앱 기준선 (이전 상태 스냅샷)

기존 스냅샷 기준일: 2026-11-27  
저장소: `justinhblee-prog/nexus_ai`  
진행 기준: PR #1 (bootstrap) → PR #6 (backend) → PR #5 (workspace UI)  
전체 상태: **IN PROGRESS — 원격 CI 검증은 통과, Windows 실환경·OAuth 검증은 미완료**

## 1. 현재 완료 범위

- 7개 워크스페이스: Dashboard, AI Content Studio, Discovery, Review, Publishing, Analytics, Operations.
- 4개 디자인 테마: Intelligence, Creator, Global Analytics, Executive. 색상 스킨과 분리된 실제 레이아웃.
- FastAPI 브라우저 세션 인증: 기본 필수, 비밀값 미설정 시 fail-closed, 12시간 HMAC HttpOnly/SameSite 쿠키, API 및 /output 보호.
- Streamlit 운영자 인증 코드 및 동일 비밀번호 정책.
- 영속 SQLite 제작 큐, 중복 방지, lease/heartbeat, bounded retry, 실패 격리, 스케줄 idempotency. 렌더 worker는 기본 1개, 환경변수로 1–4개까지 제한하며 legacy topics.txt bridge는 단일 worker로 분리.
- 소스별 수집 상태, last-good 데이터 유지, 근거 없는 조회수·성장률·글로벌 순위 미생성.
- ffprobe QA, 사람의 최종 승인, 업로드 결과의 실제 video ID/Private 상태 검증, 불확실한 결과 격리.
- Windows PowerShell 로컬 설정/검증 스크립트.
- 정적 UI 미리보기와 실제 API 연결 모드를 명확히 구분.

## 2. 최신 원격 검증 증거

| 검증 | 결과 | 근거 |
|---|---|---|
| Python 회귀 테스트 | PASS · 82 tests | [Backend Actions run 45947633427](https://github.com/justinhblee-prog/nexus_ai/actions/runs/45947633427) |
| Docker 운영 이미지 빌드 | 진행 중(최신 head) / 이전 head PASS | 위 Actions run |
| 실제 FastAPI Uvicorn 인증 E2E | PASS | 로그인 전 API/미디어 401, 오인증 401, 로그인 쿠키 발급, 인증 후 API 200, 로그아웃 후 401 |
| 실제 세로형 MP4 렌더링 | PASS | 위 Docker integration run; H.264/AAC, 1080×1920, ffprobe QA |
| MoviePy/FFmpeg 리소스 정리 | PASS | 통합 테스트 ResourceWarning 0 |
| PowerShell 스크립트 구문 검사 | PASS | Backend Actions python-checks |
| Chromium UI 브라우저 검사 | PASS | [UI Actions run 45946023351](https://github.com/justinhblee-prog/nexus_ai/actions/runs/45946023351) |
| Vercel 정적 Preview | READY | [NEXUS Preview](https://neural-network-nymvfjc1s-justinhblee-9540.vercel.app/) |

브라우저 검사 범위: 네 테마의 서로 다른 grid 구조, 색상 스킨 독립성, 샘플 넣기/제거, Analytics 이동, 모바일 테마 전환, 로그인 쿠키와 세션 만료 재로그인.

## 3. 단계별 완료 현황

| 단계 | 상태 | 남은 완료 조건 |
|---|---|---|
| Phase 0 — 런타임·보안 기반 | IN PROGRESS | Windows 로컬 Compose 시작/재시작, Streamlit 로그인, 실환경 피드 접근 |
| Phase 1 — 개발 업무 추적 | IN PROGRESS | 작업 ID/담당/상태/PR/CI를 묶는 자동 추적·보고 루프 |
| Phase 2 — Discovery·편성 | CODE + CI PASS | Windows 네트워크에서 실제 피드별 성공률 및 복구 확인 |
| Phase 3 — 제작·QA | CODE + CI PASS | 실제 OpenAI/TTS 설정을 이용한 사용자 환경 렌더링과 재시도 확인 |
| Phase 4 — Human Approval·Private 업로드 | CODE + CI PASS | 사용자 OAuth 동의 후 테스트 채널로 Private 업로드/응답 검증 |
| Phase 5 — Analytics | PARTIAL | YouTube Analytics read-only scope 동의 및 실제 성과 데이터 수집 |

## 4. 남은 작업

1. Windows 호스트에서 `scripts/setup-local-nexus.ps1 -Start` 실행.
2. `scripts/verify-local-nexus.ps1`로 API 인증, Streamlit health, 단위·실제 렌더링 테스트 재검증.
3. 실제 Google/YouTube OAuth 클라이언트와 채널 계정 연결.
4. 테스트 채널에 명시적 승인 후 Private 업로드를 수행하고 video ID/privacyStatus를 확인.
5. YouTube Analytics read-only scope 연결 전까지 조회수·시청 지속·수익 데이터는 null로 유지.
6. 로컬 DB/영상/OAuth 토큰 백업 및 재시작 복구 확인.
7. 기능별 완료 기준을 통과한 후에만 BACKEND-01/02/03 이슈를 종료.

## 5. Preview와 배포 제한

- Preview는 정적 HTML/UI 전용입니다. FastAPI, SQLite, 작업 큐와 연결된 운영 서버가 아닙니다.
- 현재 READY Preview는 UI 소스가 마지막 변경된 커밋을 포함합니다.
- Vercel 계정의 일일 배포 한도 초과로 최신 브랜치 커밋의 새 배포가 차단될 수 있습니다. 이는 GitHub Actions 테스트 실패와 별개입니다.
- 실제 운영 API는 Docker Compose의 localhost 포트 28503, Streamlit은 28502를 사용합니다.

## 6. Git 안전 정책

- PR #1, #5, #6 모두 Draft/Open 유지. PR #5 최신 UI head: `b0c68d179717212dc7993c96786f14207b782557`; PR #6 backend head: `a4c3e6b279dee5712f242b81a871e64f7f813701`.
- main 변경, PR 병합, production deploy, force-push, 이력 재작성 금지.
- YouTube 공개 업로드 및 자동 공개 전환 금지.
- 사용자 데이터, DB, 영상, OAuth 토큰, .env를 삭제하거나 초기화하지 않음.

**전체 프로젝트는 아직 완료가 아닙니다.** 원격 코드·통합 테스트가 통과한 범위와 사용자 Windows/Google 계정이 필요한 실환경 범위를 구분합니다.
