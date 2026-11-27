# NEXUS STUDIO PRO — 현재 운영·개발 인수인계서
기준일: 2026-11-27  
저장소: `justinhblee-prog/nexus_ai`  
개발 브랜치: `fix/shorts-runtime-security-bootstrap`  
PR: [#1 — Draft](https://github.com/justinhblee-prog/nexus_ai/pull/1)

> 이 문서는 현재 브랜치의 코드와 Docker 설정을 기준으로 작성한 운영 문서입니다. 루트의 기존 `HANDOVER.md`는 이전 구현 시점의 문서이므로, 포트·워처·렌더링·업로드 관련 지침이 현재 코드와 다를 수 있습니다. 현재 운영에는 이 문서를 우선 적용하십시오.

## 1. 현재 아키텍처

- Docker Compose 서비스는 `shorts-center` 하나이며 컨테이너 이름은 `nexus_ai_shorts_center`입니다. 기존 `nexus_shorts_center` 런타임과 충돌하지 않도록 분리했습니다.
- 동일 컨테이너에서 FastAPI(Uvicorn, 8503)와 Streamlit(8502)을 실행합니다.
- 호스트 포트는 기본 `127.0.0.1:28502`(Streamlit), `127.0.0.1:28503`(FastAPI)에만 바인딩합니다. 기존 서비스의 8502/8503 포트와 겹치지 않게 분리했으며, LAN/공용 인터넷에 직접 노출하지 않습니다.
- 현재 Compose는 저장소 루트를 컨테이너의 `/app`에 바인드 마운트합니다.
- FastAPI 프로세스가 `topics.txt` 호환 입력을 SQLite 큐로 가져오고 작업을 소비합니다. FastAPI와 Streamlit의 단건·전체 제작 버튼, 일일 레이더도 모두 같은 SQLite 큐에 등록합니다. 대기/실행 중 동일 채널·주제의 중복 등록을 거부합니다. Streamlit에는 별도의 파일 감시자나 직접 렌더링 경로가 없습니다.
- 기본 DB는 `data/studio_data.db`, 렌더 결과는 `output/`, YouTube OAuth 토큰과 클라이언트 비밀 파일은 `tokens/`에 둡니다.

## 2. 접속 주소

| 화면 | 주소 | 인증 |
|---|---|---|
| Browser Studio / FastAPI | http://127.0.0.1:28503 | HMAC 서명 세션 쿠키 |
| Streamlit Studio | http://127.0.0.1:28502 | Streamlit 서버 세션 |

두 화면은 같은 운영자 비밀번호를 사용하지만 로그인 세션은 서로 독립적입니다.

## 3. 비밀정보 설정

저장소 루트의 `.env`만 사용합니다. `.env`는 Git ignore 대상이며 GitHub, 이슈, PR, 채팅에 값을 붙여넣지 않습니다.

필수 변수:
- `NEXUS_API_PASSWORD`: 12자 이상, 두 UI 공통 운영자 비밀번호
- `NEXUS_SESSION_SECRET`: 32자 이상, FastAPI 서명용 별도 랜덤 키
- `NEXUS_AUTH_ENABLED=true`: 기본값이며 운영자 인증을 필수로 적용합니다. false는 격리된 loopback 개발 환경에서만 명시적으로 허용합니다.
- `NEXUS_COOKIE_SECURE=false`: localhost HTTP 개발 환경. HTTPS 프록시를 사용할 때만 true로 전환
- `NEXUS_STREAMLIT_HOST_PORT=28502`, `NEXUS_API_HOST_PORT=28503`: 호스트 포트가 사용 중일 때만 사용 가능한 포트로 변경

PowerShell에서 비밀값을 화면에 출력하지 않고 생성하는 예:

```powershell
$ApiPassword = python -c "import secrets; print(secrets.token_urlsafe(24))"
$SessionSecret = python -c "import secrets; print(secrets.token_urlsafe(48))"
@(
  "NEXUS_API_PASSWORD=$ApiPassword"
  "NEXUS_SESSION_SECRET=$SessionSecret"
  "NEXUS_COOKIE_SECURE=false"
) | Set-Content -Path ".env" -Encoding utf8NoBOM
```

기존 `.env`가 존재하면 덮어쓰기 전에 반드시 보존 여부를 확인합니다. 비밀번호나 세션 키가 이미 설정돼 있다면 새로 만들 필요가 없습니다.

## 4. 안전한 시작·중지·상태 확인

Windows PowerShell 7에서 저장소 루트의 자동 설정/검증 스크립트를 사용할 수 있습니다.

```powershell
# .env가 없으면 운영자 비밀번호를 안전하게 입력받고 세션 키를 생성
pwsh -File .\scripts\setup-local-nexus.ps1

# Docker Compose 이미지 빌드 및 localhost 서비스 시작까지 수행
pwsh -File .\scripts\setup-local-nexus.ps1 -Start

# API 인증 차단, Streamlit health, 단위 테스트, 실제 MP4 렌더링을 검증
pwsh -File .\scripts\verify-local-nexus.ps1
```

설정 스크립트는 기존 .env 항목을 보존하며 비밀번호/세션 키 값을 출력하지 않습니다. 실행 전 기존 컨테이너·포트·데이터를 삭제하지 않습니다.


먼저 올바른 Git 작업 폴더인지 확인합니다. 현재 복구 작업 폴더는 다음과 같습니다.

`C:\Users\justo\OneDrive\Documents\0. Project\nexus_ai_shorts_clean_20261126`

서비스 상태:
```powershell
docker info --format "Engine={{.ServerVersion}}"
docker compose ps --all
```

코드가 업데이트되어 컨테이너 프로세스 재시작만 필요한 경우:
```powershell
docker compose restart shorts-center
docker compose ps
docker compose logs --tail=100 shorts-center
```

Dockerfile 또는 requirements가 바뀌어 이미지 재빌드가 필요한 경우에만:
```powershell
docker compose config --quiet
docker compose up -d --build
```

정상 종료:
```powershell
docker compose stop
```

기존 데이터 보존을 위해 일반적인 운영·점검 과정에서 `docker compose down -v`, `docker volume prune`, `git clean -xfd`를 실행하지 않습니다.

## 5. 인증 동작

### FastAPI Browser Studio
- `GET /api/session/status`
- `POST /api/session/login`
- `POST /api/session/logout`
- 로그인 성공 시 12시간 HMAC 서명, HttpOnly, SameSite=Strict 쿠키 발급
- API 및 `/output/*` 미디어는 유효한 세션 쿠키가 없으면 거부
- 필수 환경변수 누락 시 fail-closed

### Streamlit Studio
- FastAPI와 동일한 `NEXUS_API_PASSWORD` 사용
- `hmac.compare_digest`로 비교
- 인증 전에는 DB·디렉터리 초기화 등 앱 동작을 시작하지 않음
- Streamlit 세션 상태로 로그인 유지, 별도 로그아웃 지원

## 6. 제작·검수·업로드 흐름

1. 트렌드 레이더가 KR/US/JP/GB의 Google News RSS, BBC 및 Hacker News 소스를 조회합니다.
2. 피드별 마지막 시도/성공 시각, 항목 수, 연속 실패 수, 마지막 오류를 `source_health`에 기록합니다.
3. 제작 요청은 SQLite `topic_queue`에 채널별로 저장되고 lease·재시도·실패 격리 규칙으로 처리됩니다. `topics.txt`는 호환 입력 브리지입니다.
4. 렌더 후 ffprobe가 파일 존재/크기, H.264, AAC, 1080x1920, 오디오 트랙, 1~180초 길이를 검사합니다. 실패한 영상은 검수 대기열에 들어가지 않습니다.
5. Browser Studio와 Streamlit 모두 검수 승인·반려·수정 저장·재검수 복귀를 지원하며 결정 이벤트를 기록합니다.
6. 업로드 요청은 SQLite 조건부 상태 전이로 한 요청만 선점할 수 있습니다.
7. 업로드 완료로 처리하려면 YouTube 응답에 영상 ID와 `privacyStatus=private`가 확인돼야 합니다. 업로드 응답이 모호하면 `업로드 상태 확인 필요`로 격리하고 중복 재시도를 차단합니다.
8. Public 게시 및 공개 전환 자동화는 없습니다. 최종 사람 승인 없이 업로드하지 않습니다.

## 7. 운영 데이터와 모니터링

- `topic_queue`: pending/running/completed/failed 작업
- `scheduler_runs`: 일일 스케줄 상태·lease·재시도
- `pipeline_jobs`: 렌더링·검수·업로드 단계
- `audit_events`: 큐, 렌더, QA, 스케줄러, 검수, 업로드 및 삭제 이벤트
- `source_health`: 소스별 수집 성공·실패 이력
- Browser Studio의 Live Operations 패널은 큐 상태, 검수 대기, 피드 상태, 최근 이벤트를 15초마다 갱신합니다.

보호된 API:
- `GET /api/events?limit=50`
- `GET /api/ops/metrics`

## 8. 백업·복구

업데이트나 복구 작업 전에 아래 항목을 별도 보안 위치에 백업합니다.
- `data/` (SQLite DB)
- `output/` (생성 영상)
- `tokens/` (OAuth 토큰 및 클라이언트 설정)
- `.env` (운영 비밀정보)

`.env`와 `tokens/` 백업은 암호화된 저장소에 보관하고 공유하지 않습니다. OneDrive 동기화만을 유일한 백업으로 간주하지 않습니다. 복구 시 DB와 영상 경로를 먼저 보존한 뒤 앱 코드를 교체합니다.

## 9. 검증 현황과 미완료 사항

2026-11-27 기준 원격 검증:
- Backend CI [run #45946478308](https://github.com/justinhblee-prog/nexus_ai/actions/runs/45946478308): 80개 단위 테스트, Docker Compose 검증, Python compile, PowerShell 구문 검사 통과.
- 동일 Docker integration run: 실제 Uvicorn 프로세스에서 미인증 API/미디어 401, 오인증 401, 로그인 후 API 200, 로그아웃 후 401 확인.
- 동일 Docker integration run: 실제 1080×1920 H.264/AAC MP4 렌더링 및 ffprobe QA 통과. MoviePy/FFmpeg ResourceWarning 0.
- UI Playwright [run #45946023351](https://github.com/justinhblee-prog/nexus_ai/actions/runs/45946023351): 네 가지 테마, 색상 독립성, 샘플 토글, 워크스페이스 이동, 모바일 전환, HttpOnly/SameSite 로그인 쿠키와 세션 만료 재로그인 통과.
- Vercel Preview는 [READY 주소](https://neural-network-nymvfjc1s-justinhblee-9540.vercel.app/)에서 확인할 수 있습니다. 정적 UI 미리보기이며 FastAPI/SQLite 운영 백엔드와 연결된 주소가 아닙니다.
- Vercel 무료 배포 일일 한도 초과로 최신 브랜치 커밋의 새 배포가 제한될 수 있습니다. 기존 READY 미리보기의 UI 소스는 현재 UI 코드와 동일합니다.
- 위 CI 결과는 Windows 로컬 실행, 실제 뉴스 피드 가용성, 실계정 OAuth 또는 실제 YouTube 업로드를 대신하지 않습니다.

아직 Windows 호스트에서 직접 확인해야 하는 항목:
- 기존 Docker 컨테이너와 현재 브랜치 코드의 안전한 연결 및 실제 로그인
- Windows 호스트에서 scripts/setup-local-nexus.ps1 -Start 및 scripts/verify-local-nexus.ps1 실행
- 실제 뉴스 피드 접근 성공률 및 재시작 후 큐/스케줄 복구
- 채널별 OAuth 및 테스트 채널 YouTube Private 업로드/응답 확인
- YouTube Analytics read-only scope 동의와 실제 성과 수집
- 백업·복구 및 기존 데이터 보존 검증
## 10. GitHub 작업 정책

- 기준 브랜치는 `fix/shorts-runtime-security-bootstrap`이며 후속 변경은 PR #6 Backend와 PR #5 UI에서 분리 관리합니다.
- PR #1, #5, #6은 Draft/Open 상태로 유지합니다.
- `main` 직접 수정, 병합, 운영 배포, 강제 푸시, 이력 재작성은 하지 않습니다.
- 로컬 기존 DB·영상·토큰·환경설정은 저장소 복구를 이유로 삭제하거나 초기화하지 않습니다.

## 11. Product design baseline

The product design decisions carried forward across repository migration are recorded in [docs/NEXUS_PRODUCT_DESIGN_BASELINE.md](NEXUS_PRODUCT_DESIGN_BASELINE.md). This is the source of truth for the single Monochrome default theme, the four additional comparison themes, the seven-workspace navigation, and the existing Dashboard reference assets. Do not substitute a new theme list or dashboard layout.
