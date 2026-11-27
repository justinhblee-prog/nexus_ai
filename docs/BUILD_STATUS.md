# NEXUS STUDIO PRO — BUILD STATUS

기준일: 2026-11-27  
저장소: `justinhblee-prog/nexus_ai`

## 최신 Hosted SaaS 릴리스 상태

**IN PROGRESS · PR #11 Draft/Open · 운영 전환 차단**

- 작업 브랜치: `feat/nexus-user-onboarding-web-oauth-20261127`
- 현재 PR branch head: `7369889a95c3f695663d635da01cdc1a3cead7ac` (Topic Queue RLS viewer read/editor write 권한 수정 포함)
- 마지막 성공 CI: run `46021232590`, head `1c06415b01e3fadcc52c6a9ee57e09ef636319dd`, 315 tests PASS. 중간 수정 커밋 `aa89daffe6745d09feaa6e31ff3eab2b7faf565b` CI는 정책 회귀 테스트 실패로 확인되어, 정책을 재수정한 현재 head의 새 검증은 아직 확인 전.
- Pull Request: [#11 — User onboarding and hosted OAuth](https://github.com/justinhblee-prog/nexus_ai/pull/11)
- 마지막 성공 GitHub Actions: [run 46021232590](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46021232590) — exact head `1c06415b01e3fadcc52c6a9ee57e09ef636319dd`에서 **315 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, Playwright browser smoke 모두 통과. 이후 Topic Queue 권한 정책 변경은 현재 head에서 새 CI 통과를 확인해야 함.
- PR은 Draft/Open이며 merge하지 않음. main push, production deployment, public YouTube upload 금지.
- Supabase 서비스 프로젝트 `ai_studio` (`lmdhgqfqvfyymfrovaty`)는 ACTIVE_HEALTHY, PostgreSQL 17.11, Seoul ap-northeast-2, Free plan.
- 현재 운영 DB migration history는 총 14개(NEXUS foundation/auth/workspace/OAuth/render/upload 기반). 계정 삭제/권한 강화 후속 6개는 미적용.
- 현재 Supabase public/private 테이블 목록에 `public.shorts_topic_queue`와 account-deletion 전용 private 테이블이 없음. Saved topic queue는 UI/API 코드와 설계 SQL까지 구현됐지만 DB migration 생성/적용 전이므로 서버 저장 모드는 아직 활성화 불가.
- 실데이터가 아직 없는 상태: 확인된 workspace/Shorts tenant 테이블 행 수는 0. 실제 Google OAuth 및 2개 계정 간 tenant E2E는 검증되지 않음.

### 코드/CI 완료 범위

- Supabase Auth signup/login/password recovery 및 사용자별 workspace API/UI.
- Workspace RLS 기반 exact-count overview, paginated job history, workspace 전환 stale-response 방지.
- Owner/admin 전용 최종 승인 및 conditional state update.
- Vercel FastAPI entrypoint 분리. 로컬 Streamlit `app.py`는 유지하며 Hosted cold start는 로컬 SQLite/worker/scheduler를 시작하지 않음.
- OAuth PKCE/state, encrypted token vault, private render/upload worker, private-only YouTube upload path, account-deletion retry/checkpoint 설계 및 테스트. OAuth 시작 후 Google 왕복 중 workspace admin 권한이 강등/삭제되는 경우를 막기 위해 callback에서 code exchange 전과 credential persistence 직전에 현재 membership role을 재검증함.
- Saved topic queue 사용자·워크스페이스 scoped list/add/delete API와 UI, browser-local fallback 및 migration handoff 문서.
- Hosted trend radar endpoint는 로컬 SQLite를 쓰거나 초기화하지 않으며, Vercel 번들에 데이터 snapshot이 없을 때 unavailable 상태로 fail closed.

### Vercel Preview 현황

- 프로젝트: `neural-network` / Free plan.
- Preview 환경변수 목록에는 `NEXUS_SUPABASE_URL`, `NEXUS_SUPABASE_PUBLISHABLE_KEY` 두 레코드만 확인됨(이 브랜치 Preview 전용). 민감 값은 복호화/출력하지 않아 유효성은 미검증. Hosted server-side secret 변수 레코드는 확인되지 않음.
- 현재 READY Preview: deployment `dpl_4peW8RQNxPiwbwVkPwbWSHbawyp6`, commit `0dda21d543f8ca08ca0d98f2ecfac39c159fa425`. 최신 PR branch head `7369889...`와는 migration/test/docs 수정 커밋 차이가 있어, 해당 최신 소스의 Preview 배포 상태는 별도 확인 대상. 기존 READY는 Hosted OAuth E2E 성공을 의미하지 않음.
- Google Cloud 기존 OAuth 설정은 `NEXUS STUDIO PRO` External consent screen, test user, YouTube Data API/Analytics API, OAuth client `NEXUS STUDIO PRO Local`(Desktop application)으로 확인됨. 이 Desktop client는 로컬 `tokens/client_secret.json` 기반 localhost 인증용이며, Hosted HTTPS callback용 Web application client와 다름. 따라서 기존 Google 설정을 다시 만들 필요는 없지만, Hosted callback을 위해 별도의 Web application OAuth client와 redirect URI가 필요함.
- Vercel 프로젝트의 현재 Preview 변수 목록에는 다음 Hosted server-side 설정이 없음: `NEXUS_SUPABASE_SERVICE_ROLE_KEY`, `NEXUS_TOKEN_ENCRYPTION_KEY` 또는 `NEXUS_TOKEN_ENCRYPTION_KEYS_JSON`, `NEXUS_GOOGLE_OAUTH_CLIENT_ID`, `NEXUS_GOOGLE_OAUTH_CLIENT_SECRET`, `NEXUS_GOOGLE_OAUTH_REDIRECT_URI`, `NEXUS_HOSTED_APP_URL`. 어떤 비밀값도 채팅에 요청하거나 출력하지 않음. `NEXUS_SUPABASE_JWT_ISSUER` 및 `NEXUS_SUPABASE_JWKS_URL`은 프로젝트 URL 기본값을 사용할 수 있음.

### Supabase read-only advisor 결과 (2026-11-27 재점검)

- Health advisor: findings 0.
- Security advisor: INFO 6건, 모두 RLS가 활성화됐지만 client policy가 없는 `private.*` worker/OAuth 테이블. 의도된 service-only 접근 영역으로 기록됨.
- Performance advisor: unindexed foreign keys 14건, unused index 26건. 14개 FK를 커버하는 additive migration 파일은 PR에 있으나 live DB에는 미적용. 26개 unused index는 실제 workload 근거 없이 삭제하지 않음.
- 운영 DB에는 이번 점검에서 DDL, migration, 데이터 변경을 수행하지 않음.

### 남은 릴리스 게이트 — 모두 해소 전까지 운영 전환 금지

1. **Topic queue migration**: `20261127143658_nexus_user_workspace_topic_queue.sql` is present on PR #11 and remains unapplied to the live DB. RLS read is available to owner/admin/editor/viewer; insert/delete are restricted to owner/admin/editor, matching the workspace domain role model. Migration lint, local database application, and two-user RLS isolation tests remain pending. The active Supabase database remains unchanged.
2. **Account deletion / security migrations**: 아래 6개 파일을 review 후 별도 승인된 migration window에서 적용하고 live schema/advisor 재검증해야 함:
   - `20261127110000_nexus_account_deletion_safety.sql`
   - `20261127123000_nexus_account_deletion_oauth_retry_state.sql`
   - `20261127130000_nexus_foreign_key_index_coverage.sql`
   - `20261127140000_nexus_account_deletion_retry_lookup.sql`
   - `20261127150000_nexus_youtube_disconnect_retry_state.sql`
   - `20261127160000_nexus_anon_privilege_hardening.sql`
3. **Hosted trend persistence**: shared persistent trend snapshot/source 및 수집 파이프라인이 필요. 현재는 데이터가 없으면 unavailable로 표시.
4. **Google OAuth**: Vercel Preview에 Google client ID/secret, redirect URI, app URL, encryption key 및 필요한 server-only key를 안전하게 등록하고 Google Console redirect URI를 일치시킨 뒤 실제 동의/refresh/revoke를 테스트해야 함.
5. **Tenant E2E**: 실제 두 사용자 계정으로 같은 workspace 및 서로 다른 workspace의 read/write/delete 격리 검증이 필요. 현재 DB에는 테스트 계정이 없어 완료되지 않음.
6. **Preview runtime**: Vercel 무료 배포 한도 해제 후 최신 branch head `3643e9c2...`의 Preview를 배포하고 signup/login/API/browser smoke를 수행해야 함. 기존 READY Preview는 최신 head 증거가 아님.
7. **Account deletion / workers / upload**: 실제 계정·Google 동의·migration·private Storage prerequisites 및 E2E 전까지 `NEXUS_ACCOUNT_DELETION_ENABLED`, `NEXUS_ACCOUNT_DELETION_WORKER_ENABLED`, `NEXUS_HOSTED_WORKER_ENABLED`, `NEXUS_HOSTED_UPLOAD_ENABLED`는 false 유지. YouTube 업로드는 명시적 승인 후 Private만 허용.

### 안전 경계

- PR #11 Draft/Open 유지. merge, main push, production deploy 금지.
- Supabase 운영 migration/DDL 미적용. `ai_studio_test` dormant 프로젝트 보존.
- 유료 API, 유료 인프라, 플랜 업그레이드 금지.
- Google/OAuth/Vercel/Supabase 비밀값을 채팅이나 Git에 입력하지 않음.
- 공개 YouTube 업로드 및 자동 공개 전환 금지. 계정 삭제는 prerequisite 완료 전 비활성화.
- 다음 로컬 의존 작업 외의 코드/CI 완료 사항은 최신 head 및 Actions run으로 추적.

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

### OAuth callback authorization revalidation — 2026-11-27
- Public Google OAuth callback consumes the one-time state and then rechecks that the initiating user is still owner/admin of the same workspace before exchanging the authorization code.
- It checks the membership again immediately before privileged connection/credential persistence, so a role downgrade during the Google round trip cannot retain previously granted admin authority.
- Regression tests cover both a role already downgraded at callback entry and a role downgraded during code exchange. Latest CI run 46016494231 passes 311 tests and browser smoke.

### 최신 검증 정합성 갱신 — 2026-11-28
- 기준 브랜치 HEAD: `3fcda1e3219bd10f24dcbb1cdd1d26c741630e82`.
- GitHub Actions [run 46019730037](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46019730037) — 위 HEAD와 정확히 일치하며 전체 workflow가 성공.
- 확인된 단계: Docker Compose 설정 검증, Python 모듈 컴파일, 브라우저 JavaScript 구문 검사, Python 회귀 테스트, Playwright 브라우저 상호작용 검증이 모두 성공.
- PR #11은 Draft/Open/unmerged 상태를 유지한다.
- 이전 문단의 `3643e9c2...` / run `46016494231`은 과거 검증 기록이며 현재 최신 검증 기준이 아니다.
- 운영 전환을 막는 외부 게이트는 그대로다: 최신 Preview 런타임 배포(무료 일일 quota 해제 필요), Supabase 후속 migration 별도 승인·적용, 안전한 OAuth 서버 환경변수 등록 및 실 Google 동의/refresh/revoke, 실제 2계정 tenant E2E, 실제 Private 업로드 E2E. 현재 대화 세션에서는 사용자의 로컬 Windows 런타임 및 Google 계정에 접근할 수 없으므로 이를 완료로 표시하지 않는다.
- 이 기록은 상태 문서만 갱신하며 운영 DB, Vercel 배포, 워커 활성화, YouTube 업로드에는 영향을 주지 않는다.

### Preview 재개 확인 — 2026-11-28
- Vercel Free quota 제한 이후 새 Preview 배포가 재개됨. Deployment `dpl_4peW8RQNxPiwbwVkPwbWSHbawyp6`는 `READY`, target `Preview`, branch `feat/nexus-user-onboarding-web-oauth-20261127`, exact commit `0dda21d543f8ca08ca0d98f2ecfac39c159fa425`로 확인됨.
- 이는 빌드/배포 상태가 READY라는 뜻이며, 실제 signup/login, Supabase API, OAuth, tenant isolation의 runtime E2E 성공을 뜻하지 않는다. 브라우저 상호작용 smoke는 GitHub Actions에서 별도로 통과해야 하며, 외부 OAuth/실계정 검증은 별도 gate로 유지한다.
- 이전의 "새 Preview 배포가 quota로 차단" 문구는 과거 상태다. 최신 READY 배포 기록이 이를 대체한다.
