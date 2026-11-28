# NEXUS STUDIO PRO — BUILD STATUS

기준일: 2026-11-28  
저장소: `justinhblee-prog/nexus_ai`

## 최신 Hosted SaaS 릴리스 상태

**CODE + CI VERIFIED · LIVE ACTIVATION / USER E2E PENDING**

- 작업 브랜치: `feat/nexus-user-onboarding-web-oauth-20261127`
- PR #11 현재 상태: Draft / Open / Unmerged. [PR #11](https://github.com/justinhblee-prog/nexus_ai/pull/11)
- 최신 app-code GitHub Actions [run 46046048384](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46046048384) 성공: **343 Python tests PASS**, Docker Compose validation, Python compilation, browser JavaScript syntax, Playwright browser interaction smoke.
- 최신 Supabase local migration validation [run 46046048450](https://github.com/justinhblee-prog/nexus_ai/actions/runs/46046048450) 성공: **22개 migration 전체를 빈 local Supabase stack에 순서대로 적용**, privileged ACL script를 local `supabase_admin` 역할로 실행해 `storage.objects` anon SELECT = false 및 public default ACL anon entries = 0 확인, `supabase db lint --fail-on error`에서 `No schema errors found`.
- 기존 PR #1, #5, #6, #7, #8, #9, #10은 Draft/Open으로 보존. PR #5와 #7은 이후 통합 PR에서 기능이 이어진 과거 브랜치로 PR 대화에 상태를 기록함.
- Supabase `ai_studio` (`lmdhgqfqvfyymfrovaty`)는 ACTIVE_HEALTHY, PostgreSQL 17.11, Seoul region, Free plan. Live migration history는 14개이며 아래 8개 후속 migration은 아직 적용하지 않음.
- Live Supabase에는 Auth 사용자/workspace/Shorts tenant 데이터가 없고, `public.shorts_topic_queue`, `public.public_trend_signals`, `public.public_trend_scans` 테이블도 아직 없음. 합성 사용자/데이터는 생성하지 않음.
- SaaS auth/workspace, trend reader/collector, topic queue API/UI, private render/review/upload, account-deletion 설계는 코드와 회귀 테스트에 포함됨. 실제 Google/YouTube 계정과 두 사용자 기반 E2E는 별도 검증 필요.

### 코드 및 CI 검증 완료 범위

- Supabase Auth signup/login/password recovery 및 사용자별 workspace bootstrap, JWT 검증, tenant-scoped APIs.
- Workspace RLS 기반 exact-count overview, job history, workspace 전환 stale-response 방지.
- Owner/admin 전용 최종 승인과 conditional state update.
- Vercel FastAPI entrypoint 분리. 로컬 Streamlit `app.py`는 유지하며 Hosted cold start는 로컬 SQLite/worker/scheduler를 시작하지 않음.
- Google OAuth PKCE/one-time state, encrypted refresh-token vault, callback membership 재검증, channel discovery 및 disconnect lifecycle.
- Private Storage, render/review/approval, private-only YouTube upload path, upload lease/checkpoint, account-deletion retry/checkpoint 코드 및 회귀 테스트.
- 사용자·workspace scoped saved topic queue API/UI와 browser-local fallback. 서버 저장형 queue는 migration 적용 전까지 live에서 사용할 수 없음.
- Hosted shared trend reader/collector 구현. Worker는 source별 최신 데이터 upsert 후 성공한 source만 오래된 행을 정리하며, 실패 source의 마지막 정상 데이터는 보존. 일일/주간 scan 실패는 health metadata를 게시하고 다른 period도 시도한 뒤 worker retry loop로 전달.
- CLI-generated shared trend migration: `supabase/migrations/20261127172712_nexus_shared_public_trend_store.sql`.
- 로컬 migration replay 중 발견한 SQL 오류를 수정함:
  - `character_bundle_imports.user_id`는 composite primary key이므로 nullable로 바꾸지 않음. Auth 삭제 시 계정별 idempotency 기록은 FK cascade로 제거.
  - account-deletion migration이 worker claim 함수를 다시 정의할 때 `ON CONFLICT (job_id)`가 PL/pgSQL 출력 변수와 모호해지는 문제를 named constraint `shorts_worker_leases_pkey`로 수정.
  - 일반 migration은 `postgres` 실행 role이 변경할 수 없는 `supabase_admin` default ACL을 수정하지 않도록 분리. 별도 관리자 작업은 아래 문서 참조.

### Supabase local migration validation

- Live `supabase_migrations.schema_migrations` read-only metadata contained five historical ACS migrations that were missing from the repository: `20261106082748`, `20261106082803`, `20261106082842`, `20261106082905`, and `20261106083604`.
- Restored the exact original SQL statements stored in those live migration records as five version-matched files under `supabase/migrations/`. These are original historical migrations, not no-op placeholders or reconstructed guesses; no live migration history was modified.
- The repository now contains 22 migration files: 5 historical ACS + 9 already-applied NEXUS foundation + 8 pending NEXUS follow-ups.
- The local workflow starts an empty isolated Supabase stack and applies all 22 actual repository migrations in timestamp order. It no longer relies on a test-only legacy schema fixture.
- Full 22-file replay passed. The privileged admin ACL operation also passed in the isolated local stack, and `supabase db lint --fail-on error` reported `No schema errors found`.

### Vercel Preview 및 OAuth 설정

- 프로젝트: `neural-network`, Free plan.
- Branch-scoped Preview 환경변수 8개 확인: Supabase URL/publishable/secret key, Google Web OAuth client ID/secret/redirect URI, hosted app URL, AES-256-GCM token-encryption key. Preview + feature branch 전용이며 Production 변수는 추가하지 않음.
- 최신 READY Preview deployment: `dpl_GbToC9WRt9BfMPxdf1zif2haMtww`, app-code commit `ede1aca0bb8fe7aabe09a4e3f4d5478d1f64bddb`, branch alias:
  `https://neural-network-git-feat-nexus-user-onbo-509390-justinhblee-9540.vercel.app`.
- 현재 PR HEAD 이후 변경 파일은 migration/test/docs/workflow에 한정되며 Vercel app runtime 소스 변경은 없음. 따라서 READY Preview에는 현재 app runtime 코드가 포함되지만, live Supabase migration이 적용되었다는 뜻은 아님.
- Deployment의 최근 30분 error/fatal runtime log 조회에서는 로그가 반환되지 않았음. 이는 기능 성공이나 요청 처리의 증거가 아님.
- `NEXUS_GOOGLE_OAUTH_REDIRECT_URI`와 `NEXUS_HOSTED_APP_URL`, Google Cloud authorized origin/callback은 이전 unique deployment `https://neural-network-gkefyzt27-justinhblee-9540.vercel.app`에 고정되어 있음. 현재 branch alias와 다르므로 최신 branch alias에서 시작한 OAuth가 이전 호스트로 돌아갈 수 있음. 실제 Google consent/callback/refresh/revoke E2E 전에 URL 정합성 조정 필요.
- Vercel Preview SSO/deployment protection은 유지 중이며 임의 해제하지 않음. 실제 OAuth callback이 이 보호 정책을 통과하는지도 확인되지 않음.

### Supabase live read-only 점검

- Health advisor: findings 0.
- Security advisor: INFO 6건 — RLS가 활성화됐으나 client policy가 없는 private worker/OAuth tables. 의도된 service-only 접근 영역.
- Performance advisor: unindexed foreign keys 14건, unused indexes 26건. 14개 FK index coverage migration은 CI replay/lint 통과했으나 live 미적용. 26개 unused indexes는 workload 근거 없이 삭제하지 않음.
- 14개 public tenant/legacy tables에 `anon` direct table grants가 존재하지만 RLS 정책은 authenticated 역할만 대상으로 함. 정규 migration은 이 14개 테이블과 `postgres`가 생성할 미래 public table의 anon defaults를 정리하도록 작성됨. 아직 live 미적용.
- `storage.objects`에도 `anon` direct grants가 있으나 RLS가 켜져 있고 anon policy가 없으며 현재 Storage bucket은 모두 private. 이 grant는 defense-in-depth 정리 대상.
- `postgres`는 `supabase_admin`의 member가 아니므로 일반 migration role로 `supabase_admin` default ACL 및 `storage.objects` owner grant를 수정할 수 없음. 별도 operation `supabase/operations/nexus_admin_anon_acl_hardening.sql`은 CI의 격리 local stack에서 `supabase_admin` 역할로 실행·검증됨. Live 프로젝트에는 아직 실행하지 않음. 자세한 내용은 `docs/SUPABASE_ADMIN_DEFAULT_PRIVILEGES.md` 참조.
- 이번 read-only 점검과 CI migration replay에서는 live DDL, migration, 데이터 변경을 수행하지 않음.

### 남은 릴리스 게이트

1. **Live Supabase migrations** — 아래 8개는 local replay/lint PASS, live 미적용. 별도 승인된 migration window에서 review/apply 필요:
   - `20261127110000_nexus_account_deletion_safety.sql`
   - `20261127123000_nexus_account_deletion_oauth_retry_state.sql`
   - `20261127130000_nexus_foreign_key_index_coverage.sql`
   - `20261127140000_nexus_account_deletion_retry_lookup.sql`
   - `20261127143658_nexus_user_workspace_topic_queue.sql`
   - `20261127150000_nexus_youtube_disconnect_retry_state.sql`
   - `20261127160000_nexus_anon_privilege_hardening.sql`
   - `20261127172712_nexus_shared_public_trend_store.sql`
2. **Privileged ACL follow-up** — `supabase_admin` public default ACL과 `storage.objects` anon direct grant 정리는 일반 migration role로 수행 불가. 관리자 권한 connection/지원 경로가 필요하며 `docs/SUPABASE_ADMIN_DEFAULT_PRIVILEGES.md`의 SQL은 아직 실행하지 않음.
3. **OAuth configuration alignment** — Google Cloud authorized origin/redirect URI, Vercel Preview redirect URI/app URL, branch alias 및 Preview protection 정책 정합성 조정 후 실제 Google consent/callback/refresh/revoke 검증 필요.
4. **Tenant isolation E2E** — 실제 두 사용자 계정으로 같은 workspace/서로 다른 workspace의 read/write/delete 격리 검증 필요. 현재 live Auth user count 0.
5. **Private upload E2E** — 실제 테스트 YouTube 채널 연결 후 명시적 Human approval를 거쳐 private upload 및 video ID/privacyStatus 확인 필요. 공개 게시/자동 공개 전환 금지.
6. **Windows local runtime** — 사용자 Windows Docker/Streamlit/FFmpeg 실제 시작·재시작·render·backup/recovery 검증은 이 세션에서 사용자 PC에 직접 접근할 수 없어 미완료.
7. **Hosted runtime E2E** — READY Preview와 static Playwright smoke는 확인했지만 실제 signup/login, Supabase API, tenant isolation, OAuth, worker, upload runtime E2E는 별도 검증 필요.

### 안전 경계 및 Git 정합성

- PR #11 및 기존 Draft PR은 Open/Draft/unmerged 유지. merge, production deployment, public YouTube upload, force-push, history rewrite 금지.
- Supabase live migrations/DDL 및 데이터 변경은 별도 명시적 승인 전까지 수행하지 않음.
- 유료 API, 유료 인프라, 플랜 업그레이드 금지.
- Worker flags는 기본 비활성화 유지. 계정 삭제, render/upload, trend worker를 실서비스에서 임의 활성화하지 않음.
- 알려진 Git 정책 위반 기록: test-only commit `af8aa82195c2642623b5461a623c8bd0a8c99336`가 실수로 `main`에 생성됨. 추가 main 변경/삭제/revert는 수행하지 않았으며, 별도 명시적 승인 전까지 그대로 보존.
- 비밀값은 채팅/Git에 입력하거나 출력하지 않음.


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
