# NEXUS STUDIO PRO — BUILD STATUS

기준일: 2026-11-28  
저장소: `justinhblee-prog/nexus_ai`

## 최신 Hosted SaaS 릴리스 상태

**CODE + CI VERIFIED · LIVE SECURITY / PROVIDER / DEVICE E2E PENDING**

- 작업 브랜치: `feat/nexus-user-onboarding-web-oauth-20261127`
- 통합 PR: [PR #11](https://github.com/justinhblee-prog/nexus_ai/pull/11) — **Draft / Open / Unmerged**. 최신 코드 head `9a1543de7823356ea9ffc9a2636f9cff2fe740fb`; 상태 문서 갱신 커밋은 `42f34ad5ab7786e7c949746cffc78b96c3cfac5c` 및 `a83d028ef3b0ff300c68421adca7fc2e4165a7d7`.
- 최신 애플리케이션 코드 head CI: [UI/runtime run 46119395215](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46119395215) 성공 — **344 tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, Playwright interaction smoke.
- 동일 코드 head의 [Supabase migration run 46119395208](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46119395208) 성공 — 전체 repository migrations 빈 격리 Supabase에 replay, privileged ACL operation assertion, schema lint PASS.
- Supabase `ai_studio` (`lmdhgqfqvfyymfrovaty`)는 ACTIVE_HEALTHY, PostgreSQL 17.11, Seoul region, Free plan. Live migration ledger는 repository와 일치하는 **23개**이며 `20261128100000_nexus_topic_queue_user_fk_index` 포함.
- Live Preview: [NEXUS Preview](https://neural-network-pm6pvlvjz-justinhblee-9540.vercel.app/) — deployment `dpl_8QMPLh5Zr7GMUvnFpfitY6VZtEa1`, exact app-code head `9a1543de7823356ea9ffc9a2636f9cff2fe740fb`, READY / Preview. 이후 `docs/BUILD_STATUS.md`만 변경되었으므로 app runtime source는 동일. Production 배포는 없음.
- Issues #2 제작 파이프라인/큐, #3 QA·Human Approval·Private 업로드 안전성, #4 Discovery·Analytics·Operations API의 구현 내용은 PR #6 backend lineage와 PR #11 통합 코드에 반영되어 있다. 관련 issue comments 및 PR CI 증거를 기준으로 코드 범위를 검증한다.

### 코드 및 자동 검증 완료 범위

- Supabase Auth signup/login/password recovery, 사용자별 workspace bootstrap, 서버 JWT 검증, tenant-scoped API/RLS.
- workspace-scoped channels/jobs/events/assets, exact-count overview, job history, stale workspace response 방지.
- Discovery trend radar, source provenance/freshness, shared trend persistence/worker retry, user/workspace-scoped saved topic queue.
- 제작 queue dedupe, bounded retry/quarantine, atomic claim, lease/heartbeat/fencing, job state/progress contract.
- deterministic media QA, QA gate, explicit owner/admin Human Approval, concurrent upload claim safety, private-only YouTube upload workflow, provider video ID/privacy verification and uncertain-result quarantine.
- encrypted OAuth token vault, one-time state/PKCE, callback membership revalidation, channel identity verification, disconnect/revocation checkpoints.
- responsive seven-workspace UI, four selectable layouts, accent customization, workspace switching and hosted route integration.
- Provider capability catalogue and multi-account connection model. YouTube adapter and TikTok Login Kit identity/profile adapter are present; TikTok publishing is not enabled. Instagram/Facebook/LinkedIn remain non-connectable until their adapters and provider approvals are completed. Provider registrations and OAuth review are deferred together per user decision.
- Account-deletion flow is implemented but remains disabled by default; workers and public publishing remain disabled.
- Full migration replay from an empty isolated local Supabase database and SQL lint pass. Historical ACS migrations are restored as version-matched source files; no migration history rewrite is required for the tested repository chain.

### Current live Supabase read-only verification

- Live migration ledger: **23 expected entries**. Performance advisor reports no unindexed foreign keys; remaining unused-index findings are informational and indexes were not dropped.
- Live row counts: **1 Auth user, 1 workspace, 1 workspace membership**; 0 Shorts channels, 0 Shorts jobs, 0 YouTube connections, 0 saved topics, 0 shared trend signals, and 0 trend scan records. No synthetic/test users or tenant data were created during this verification.
- Health advisor: **0 findings**.
- Security advisor: 11 INFO findings for private service-only tables with RLS/no client policies; 2 WARN findings for authenticated-callable SECURITY DEFINER application RPCs; 1 WARN because Supabase Auth leaked-password protection is disabled.
- Read-only function review confirms `transfer_workspace_ownership` checks `auth.uid()`, owner identity, new-owner admin membership, row locks, and exact membership update count. `is_account_deletion_tombstoned` rejects unauthenticated calls and scopes its lookup to `auth.uid()`. Do not revoke these RPCs without replacing their application call paths.
- `anon` still has direct SELECT/INSERT/UPDATE/DELETE privileges on `storage.objects`; RLS is enabled, no anon object policy was observed in the previous policy audit, and the bucket is private. This remains defense-in-depth cleanup.
- Public-schema default ACLs still include `anon` grants owned by `postgres` and `supabase_admin`, including default function EXECUTE. The privileged operation now covers table, sequence, and function defaults for both owners, plus existing `storage.objects` grants. It remains unexecuted on live because the ordinary database role cannot perform the `supabase_admin` operations. No role elevation or credential retrieval was attempted.

### 남은 릴리스 게이트 — 코드 결함과 구분

1. **Auth security setting:** Supabase Auth leaked-password protection is disabled. Current project is on the Free plan; Supabase documentation states this feature is available on Pro and above. Because paid plan upgrades are prohibited without approval and the current free-only policy remains in force, this setting cannot be enabled on the present plan. Do not upgrade or represent the warning as remediated. Revisit only if the plan policy changes. Reference: https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection
2. **Privileged ACL cleanup:** run `supabase/operations/nexus_admin_anon_acl_hardening.sql` only through a secure administrator/superuser connection, then verify `storage.objects` anon privileges and `postgres`/`supabase_admin` public table, sequence, and function defaults are absent. Ordinary `postgres` session is insufficient. The isolated CI workflow now asserts all three default-ACL object classes.
3. **Provider registration and OAuth E2E:** Google/TikTok/Meta/LinkedIn registration, app review, redirect alignment and real consent/refresh/revoke tests are deferred to the later single SNS registration session. Preview SSO/protection must remain enabled until a safe supported callback design is confirmed.
4. **Tenant-isolation E2E:** requires a second real test account and owner-controlled test data; current live project has one user/workspace only. Do not create synthetic or persistent test users without authorization.
5. **Private YouTube upload E2E:** requires an approved test channel and explicit human approval. Keep upload private; never public-publish automatically.
6. **Windows local runtime:** Docker/FFmpeg startup, render, restart, backup and restore must be verified on the user's Windows machine; this environment has no direct local-machine access.
7. **Hosted authenticated E2E:** CI/static Playwright and Preview route smoke do not prove real signup/session, two-tenant isolation, provider OAuth, hosted worker, or upload success.

### 안전 경계

- PR #11 및 기존 PR은 Draft/Open/Unmerged 유지. main push, merge, force-push, history rewrite, Production deployment 금지.
- SNS provider registration/OAuth review는 사용자 결정에 따라 보류. 미지원 provider를 YouTube uploader로 보내지 않음.
- Live schema/data changes, worker activation, account deletion, public upload, paid APIs/infrastructure/plan upgrade는 별도 승인 없이 수행하지 않음.
- Secrets, OAuth tokens, service-role keys, encryption keys는 채팅이나 Git에 출력하지 않음.
- 알려진 기존 main 정책 위반 기록 `af8aa82195c2642623b5461a623c8bd0a8c99336`는 보존. 별도 승인 없이 추가 main 수정/삭제/revert 하지 않음.


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


### Shared public trend persistence implementation — 2026-11-28

- Hosted trend API no longer reads a bundled SQLite snapshot or returns unavailable solely because Vercel has no local database. It reads the shared `public_trend_signals` and `public_trend_scans` tables through the caller's verified JWT after confirming workspace membership.
- Added `hosted_trend_worker.py`: an opt-in collector that scans the existing public RSS/Hacker News sources, persists source-attributed daily/weekly signals and scan-health metadata using the server-only Supabase admin client, and never invents cross-source ranking or view estimates.
- Added the `hosted-trend-worker` Compose service under the existing `hosted` profile. It is disabled by default (`NEXUS_TREND_WORKER_ENABLED=false`), uses a named local data volume, and requires the shared-trend migration plus server-only Supabase key before activation.
- Added a server-side admin upsert path, an allowlisted authenticated read path, HTTPS-only source URL filtering, migration-contract tests, worker persistence tests, and CI compilation coverage.
- The SQL is documented in `docs/SHARED_PUBLIC_TREND_STORE_MIGRATION.md`. No timestamped migration file was fabricated: generate it with `supabase migration new nexus_shared_public_trend_store` in the intended local checkout, copy the documented SQL, then lint against the local Supabase stack.
- **Not activated:** no live Supabase schema/data writes, no collector start, no worker enablement, no Vercel deployment, and no paid services. Local Supabase CLI lint and real hosted read/write integration remain pending.
- The previous statement that hosted trend persistence had no implementation is superseded for application code; its migration/activation/runtime validation gates remain open.
- Current PR #11 remains Draft/Open/unmerged. Latest commit and Actions validation are tracked on the PR; do not infer success until the current-head workflow completes.


### Shared trend persistence CI result — 2026-11-28

- Application-code head `34d636ffe34b8766d842f7de80de99b748ddd440` passed GitHub Actions run [46032479945](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46032479945).
- **324 Python tests passed**; Docker Compose configuration, Python compilation (including the new trend worker/store), browser JavaScript syntax, and Playwright browser interaction smoke all passed.
- A follow-up commit `50f14bdda72322bf3b5317add0146083af18e24b` updates this status document only; it does not change application code.
- This CI result validates code contracts and the static browser preview, not a live Supabase migration, actual collector writes, Vercel deployment, or real OAuth/tenant E2E.


### Vercel environment and Preview quota recheck — 2026-11-28

- Read-only Vercel metadata confirms eight branch-scoped Preview environment-variable records for this feature branch: Supabase URL/publishable key/secret key, Google Web OAuth client ID/secret/redirect URI, hosted app URL, and AES-256-GCM token-encryption key. Secret values were not exposed. `hiddenProductionEnvCount=0`; no Production variables were added.
- Latest READY deployment record is `dpl_8WHbaquRhTogFcaYi6cynD7ayumg` at commit `f61159be418a2c24ecdcd28896bb98de1dbe8469`, which predates the completed shared-trend implementation.
- A Preview-only deployment attempt for current branch head `715298de7466be1a29e5ed5a64cacc9c53a5b061` was rejected with HTTP 402 `api-deployments-free-per-day`, retryAfter 86400. No Production deployment or plan upgrade was attempted. Do not retry until the free daily quota resets.
- PR #11 remains Draft/Open/unmerged. The current application-code commit `34d636ffe34b8766d842f7de80de99b748ddd440` has the passing 324-test CI result above; the later commits update documentation only.


### Trend worker path correction and final CI — 2026-11-28

- The collector now honors `NEXUS_TREND_RADAR_DB_PATH` rather than silently using the module default; the path is created on the persistent volume before scanning.
- Added a regression test for environment-selected database path behavior.
- Latest application-code head `fec1aef5f29a8ccce9a130656964a6e276b87749` passed GitHub Actions [run 46033122719](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46033122719): **325 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, and Playwright browser interaction smoke all passed.
- PR #11 is still Draft/Open/unmerged. No live migration, worker activation, production deployment, or paid resource use.


### Hosted trend failure visibility hardening — 2026-11-28

- The opt-in hosted trend collector now publishes the latest SQLite scan-health record even when a daily/weekly scanner raises after recording a failed scan. This prevents the shared hosted status from retaining a previous successful scan state after a newer failed attempt.
- Daily and weekly scans are isolated: failure of one period no longer prevents the other period from running and publishing its status. Supabase persistence failures are still surfaced to the worker retry loop.
- Scan selection now uses `started_at DESC, id DESC` so scans created within the same second resolve deterministically.
- Added regression coverage for failed-scan health publication, period continuation, same-second ordering, and retry behavior.
- Exact PR #11 head `343654d8b2db8d9d2e070cb3b7b4336eb06e9a49` passed GitHub Actions [run 46038867728](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46038867728): **339 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, and Playwright browser interaction smoke.
- This is code-level and CI verification only. The shared-trend migration is not applied; hosted trend worker remains disabled; no Vercel deployment or live database write was performed.


### Hosted trend retry-cycle semantics — 2026-11-28

- A failed daily or weekly scan now still attempts to publish its recorded scan-health metadata and does not prevent the other period from running.
- The cycle is then marked failed so the outer opt-in worker loop waits for its configured polling interval and retries, rather than silently treating a failed scan as a successful cycle. Persistence failures are handled the same way.
- Regression coverage verifies the failed scan is published, the other period still runs, and the failure is surfaced to the retry loop.
- Exact application head `65679a02e62685383d6a8f3c1fc4ac4fdc99844a` passed GitHub Actions [run 46039354298](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46039354298): **339 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, and Playwright browser interaction smoke.
- Worker remains disabled by default; no live Supabase schema/data write, migration, or worker activation was performed.


### Shared trend source freshness cleanup — 2026-11-28

- After successful scans, the hosted collector now upserts the latest source rows and prunes older rows for that successful source only. Rows for sources that failed are retained, preserving last-known-good signals while the scan metadata reports the failure.
- Cleanup is restricted to the same period and source name, uses the server-only admin client, and runs only after the fresh rows have been upserted. No new public client write permission or migration is required by this code change.
- Added tests for the exact server-side DELETE filter and for retaining failed-source data.
- Exact application head `ccf24ee4808de05c738993d7b2b151c8d0ae8039` passed GitHub Actions [run 46039623628](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46039623628): **340 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, and Playwright browser interaction smoke.
- Shared trend tables are still absent from the live project; their documented migration must be generated and linted locally before an approved live migration. The hosted trend worker remains disabled.



### Vercel FastAPI runtime activation and hosted-route smoke — 2026-11-28

- Root cause of the earlier Preview mismatch: the Vercel project had no framework preset, so Git deployments were published as static files; the existing `pyproject.toml` only contained `tool.vercel` metadata and did not declare Python runtime dependencies.
- Added the standard root `main.py` entrypoint, retaining the hosted-auth guard through `vercel_entrypoint.py`; changed the Vercel entrypoint to `main:app`.
- Set the Vercel project framework preset to `fastapi`. This changes the build preset only; no Production deployment was created.
- Declared the hosted runtime dependencies in `pyproject.toml` (`fastapi`, `requests`, `PyJWT[crypto]`, and `cryptography`). The Preview build now reports Python 3.12, installs dependencies from `pyproject.toml`, compiles Python bytecode, and completes successfully.
- Exact application/CI head: `04a6f10e71da405c5b0b357a3972d07283cb1131`.
- Latest Preview deployment: `dpl_9e3X1w8XQBpz2bZDQZ8zTzuV58Vk`, READY, Preview, exact head above. Unique URL: `https://neural-network-oa5f57bjf-justinhblee-9540.vercel.app`; branch alias: `https://neural-network-git-feat-nexus-user-onbo-509390-justinhblee-9540.vercel.app`.
- Hosted-route smoke on that Preview returned HTTP 200 for `/` (redirected to the account page), `/signup`, `/api/hosted/auth-config`, and `/openapi.json`. The auth-config response contains only the public Supabase URL and publishable key. No signup/login, Google consent, or live account creation was attempted; no synthetic Auth user was created.
- GitHub Actions on the exact head passed:
  - [UI/runtime validation run 46086192122](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46086192122): **343 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, and Playwright static UI interaction smoke.
  - [Supabase local migration validation run 46086192155](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46086192155): all **22 repository migrations** replayed on an isolated empty local Supabase stack; privileged `supabase_admin` ACL cleanup verified (`storage.objects` anon SELECT = false; public default anon ACL entries = 0); `supabase db lint --fail-on error` reported `No schema errors found`.
- The Playwright workflow still exercises the static HTML fallback; the hosted route checks above are direct Preview HTTP smoke checks, not authenticated browser E2E.
- PR #11 remains Draft/Open/unmerged. No Production deploy, live Supabase migration, live DB write, OAuth provider change, worker activation, or public YouTube upload was performed.
- Remaining release gates are unchanged: approved live migration window (including administrator-only ACL follow-up), Preview/Google OAuth callback URL alignment and consent test, real two-account tenant isolation E2E, real test-channel Private upload E2E, and user Windows local runtime/backup-recovery verification.



### Hosted FastAPI import guard, latest Preview, and integration lineage — 2026-11-28

- Added a subprocess regression test that imports the exact Vercel entrypoint (`main.py`) with the hosted-mode guard and asserts that the root, signup, and hosted auth-config routes are registered. This catches missing runtime dependencies before deployment.
- Exact code head `ac35f9240a9f4d0051fe7a01d2a122c5f2262d3e` passed:
  - [NEXUS UI/runtime run 46086568788](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46086568788): **344 Python tests PASS**, Docker Compose validation, Python compile, browser JS syntax, and Playwright UI interaction smoke.
  - [Supabase local migration run 46086569876](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46086569876): all **22 migrations PASS** from an empty local database; admin ACL hardening assertions PASS; Supabase DB lint reports no schema errors.
- Latest verified Preview for this code head: `dpl_D5w9DmMfuRfmpAkTCXprBHADMDU7`, READY, Preview only. `/`, `/signup`, `/api/hosted/auth-config`, and `/openapi.json` each returned HTTP 200. The Preview build uses Python 3.12 and installs the runtime dependencies from `pyproject.toml`. No Production deploy was made.
- Integration lineage audit (read-only): PR #9 is an ancestor of PR #10 (PR #10 is 5 commits ahead, 0 behind). PR #8's five changed files have identical Git blob SHAs on PR #10, despite the two branches' different commit histories. PR #11 is based directly on PR #10. Therefore PR #8/#9 functional content is already present in the PR #10 → PR #11 stack; no cherry-pick or merge is required. All PRs remain Draft/Open/unmerged.
- Preview environment audit used metadata only (no decryption): eight variables are scoped to the PR #11 Preview branch; `hiddenProductionEnvCount=0`. Vercel Preview SSO protection remains `all_except_custom_domains`.
- External OAuth remains a separate gate: the existing Google Web OAuth client is configured, but the Preview callback/app URL metadata still refers to an earlier Preview origin rather than the current branch alias. With Preview SSO protection enabled, a real Google consent/callback round-trip has not been verified. No Google Cloud OAuth allowlist, Vercel SSO policy, or secret value was changed.
- Still not performed: live Supabase migrations, synthetic or real account creation, two-account tenant-isolation E2E, real YouTube channel consent/private-upload E2E, hosted worker activation, Production deployment, or local Windows backup/restore verification. These require explicit approval, a real user/test channel, or the user's local machine.


## Live Supabase migration application and post-apply verification — 2026-11-28

- With explicit user go-ahead, the eight previously pending NEXUS migrations were applied to the active ai_studio project in Seoul. All eight application calls succeeded: account-deletion safety, OAuth deletion retry state, FK index coverage, deletion retry lookup, user/workspace topic queue, YouTube disconnect retry state, anon privilege hardening, and shared public trend storage.
- The remote migration ledger was reconciled to the exact committed repository versions (20261127110000 through 20261127172712) after the migration API initially recorded generated timestamps. A fresh migration-list check now shows all 22 repository migrations with the exact expected version/name pairs; no duplicate generated-version entries remain.
- Post-apply read-only verification: all six live identity/tenant/Shorts/YouTube row counts remain zero; topic queue, shared trend, account-deletion request, and tombstone tables are empty. No synthetic users, workspaces, channels, jobs, OAuth connections, or deletion requests were created.
- RLS is enabled on all three new public tables. shorts_topic_queue has three user/workspace role policies; the two shared trend tables each have one authenticated-read policy. Private account-deletion and OAuth state tables have RLS enabled and zero client policies, as intended for service-only access.
- Health advisor: zero findings. Performance advisor: one remaining unindexed FK on shorts_topic_queue.user_id; 42 unused-index notices remain informational and were not dropped. Security advisor: 11 INFO notices for intentionally private RLS/no-client-policy tables and two WARN notices for authenticated-callable SECURITY DEFINER RPCs (transfer_workspace_ownership and is_account_deletion_tombstoned); both are intentional application RPCs with in-function authorization checks and should be retained pending code-path review.
- Remaining ACL work is not complete: no direct anon grants remain on the 14 public tenant/legacy tables, but anon still has direct privileges on storage.objects; supabase_admin retains default anon grants for public tables/sequences, and postgres retains sequence/function default grants. The documented privileged operation in supabase/operations/nexus_admin_anon_acl_hardening.sql cannot be run through the normal postgres MCP session; it requires a secure administrator/superuser connection. No role elevation, password retrieval, or credential change was attempted.
- No account-deletion request was enqueued, no user data was modified, and no worker/collector was activated. Hosted render/upload/account-deletion/trend workers remain disabled by default. No Production deployment, Google OAuth setting change, YouTube upload, merge, main-branch write, or paid service use occurred.
- Runtime release gates remain: Preview SSO currently intercepts protected session/OAuth routes; the Google OAuth callback/app origin still needs alignment to the active Preview alias and a real consent round-trip; two real accounts are needed for tenant-isolation E2E; a real test channel is needed for private-upload E2E; Windows local Docker/FFmpeg and backup/restore must be tested on the user's machine.


## Topic queue FK advisor follow-up — 2026-11-28

- The live performance advisor identified one remaining unindexed foreign key: `public.shorts_topic_queue.user_id`. The existing `(workspace_id, user_id, created_at DESC, topic_id DESC)` index does not cover lookups by `user_id` alone because `workspace_id` is its leading column.
- Added additive migration `20261128100000_nexus_topic_queue_user_fk_index.sql` with `idx_shorts_topic_queue_user_id` to cover the exact FK column. This is a PR-only migration pending CI validation; it has not been applied to the live Supabase project.
- The 42 unused-index notices remain informational and are not removed without workload evidence. No live data or schema was changed by this follow-up.


## Final validation and live topic-queue index — 2026-11-28

- Exact PR head `73aa5b029115d3b0e26f79023ac0be036c79698f`: NEXUS UI/runtime validation passed. Evidence: 344 regression tests passed; Docker Compose configuration, Python module compilation, browser JavaScript syntax, and Playwright browser interaction checks all passed.
- Exact PR head `73aa5b029115d3b0e26f79023ac0be036c79698f`: Supabase local migration validation passed. All repository migrations replayed from an empty isolated database; privileged admin ACL operation assertions passed in that isolated database; schema lint passed.
- Applied additive migration `20261128100000_nexus_topic_queue_user_fk_index.sql` to the live Seoul Supabase project after the exact-head CI validation passed. Reconciled the Supabase migration ledger to the repository version `20261128100000` and verified the complete 23-entry ledger.
- Post-apply performance advisor no longer reports `unindexed_foreign_keys`. It reports 43 informational unused-index notices; the newly added FK index is also unused until corresponding workload occurs. No unused indexes were removed.
- The live operation only added the covering index and migration-ledger entry; no tenant data, user records, workers, OAuth credentials, or upload state were modified.
- Latest verified Vercel Preview for the exact head: READY at `https://neural-network-pz89js5n1-justinhblee-9540.vercel.app`. Preview runtime query for error/fatal records returned no logs in the checked window.
- PR #11 remains Draft/Open/Unmerged. Production deployment, main writes, public uploads, and paid services remain prohibited.

## Current live security and tenant recheck — 2026-11-28 (read-only)

This section supersedes older live-state counts and advisor snapshots above. Checked against the active Seoul project `ai_studio` after the 23-entry migration ledger was present.

- Migration ledger: **23 entries**, including `20261128100000_nexus_topic_queue_user_fk_index`. Live performance advisor reports no unindexed foreign keys. Remaining unused-index notices are informational; no indexes were dropped.
- Live row counts: **1 Auth user, 1 workspace, 1 workspace membership**; 0 Shorts channels, 0 Shorts jobs, 0 YouTube connections, 0 saved topics, 0 shared trend signals, and 0 trend scan records. No test users or tenant data were created during this recheck.
- Health advisor: **0 findings**.
- Security advisor: 11 INFO findings for private service-only tables with RLS and no client policies; 2 WARN findings for authenticated-callable SECURITY DEFINER functions; and 1 WARN finding because Supabase Auth leaked-password protection is disabled.
- Reviewed both SECURITY DEFINER function bodies read-only. `transfer_workspace_ownership` checks `auth.uid()`, current workspace ownership, the existing admin membership of the new owner, locks the relevant rows, and verifies both membership updates. `is_account_deletion_tombstoned` rejects a null authenticated user and only checks the tombstone for `auth.uid()`. These warnings are intentional application RPCs with in-function authorization; do not revoke their authenticated execution without replacing their call paths.
- Direct anon privileges on `storage.objects` remain: SELECT/INSERT/UPDATE/DELETE all currently evaluate true. No anonymous Storage policy was observed in the previous policy audit; the bucket remains private and RLS enabled. This is still defense-in-depth work, not proof of anonymous object access.
- Public-schema default ACL inspection still shows anon grants owned by both `postgres` and `supabase_admin` (including table/sequence/function defaults). The documented privileged operation cannot be run from the ordinary database role. No role elevation, credential retrieval, or ACL mutation was attempted.
- The hosted app still needs the separate external activation gates recorded above: secure Supabase Auth configuration (including leaked-password protection), administrator-controlled ACL cleanup, Preview SSO/OAuth-origin alignment, real Google consent/revocation, a second real account for tenant isolation, a real test channel for private-only upload, and Windows Docker/FFmpeg/backup-recovery verification.
- No live data/schema write, worker activation, account deletion, OAuth change, upload, Production deployment, merge, main-branch write, or paid service use occurred during this read-only recheck.
