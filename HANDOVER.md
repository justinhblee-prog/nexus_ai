$doc1 = @'
# 📑 NEXUS STUDIO PRO (V5.0) — 통합 기획·설계·개발 인수인계서

- **문서 버전**: V5.0 (Production Master)
- **프로젝트 경로**: `C:\Users\justo\OneDrive\Documents\0. Project\4. shorts_auto`
- **런타임 환경**: Docker Container (`nexus_shorts_center`, Linux Python 3.11)
- **서비스 접속 주소**: `http://localhost:8503`

---

## 제1부. 프로젝트 기획서 (Product Planning)

### 1. 기획 배경 및 목적
* **문제 정의**: 기존 숏폼(YouTube Shorts) 운영은 크리에이터가 직접 해외/국내 트렌드를 검색하고, 대본을 쓰고, 성우 녹음·자막 편집·업로드까지 수작업으로 처리해야 하므로 **다채널(10개 이상) 동시 운영이 물리적으로 불가능**함.
* **해결 목표**: 
  1. 글로벌 4대 권역(한국 KR · 미국 US · 일본 JP · 영국 GB)의 실시간 급상승 트렌드를 자동 수집·분석하여 **국가별 TOP 10 및 글로벌 종합 TOP 10**을 선별.
  2. 선별된 주제를 10개 특화 채널의 페르소나에 자동 매칭하고, **AI 대본 + 신경망 아나운서 음성 + 9:16 세로형 영상**을 무인 렌더링.
  3. **Human-in-the-Loop(3단 검수 워크스테이션)**를 통해 최종 승인된 영상만 YouTube Studio에 **비공개(Private)**로 안전 배포하여 저작권·품질 리스크를 원천 차단.

### 2. 타겟 글로벌 10개 채널 포트폴리오 설계

| 채널명 | 핵심 카테고리 | 타겟 페르소나 | 매칭 아나운서 성우 (Edge-TTS) | 음성 튜닝 (속도/피치) |
| :--- | :--- | :--- | :--- | :--- |
| **Future Leak** | AI · 반도체 · 미래기술 | 냉철한 테크 인사이더 | `ko-KR-InJoonNeural` (남성) | `+12%` / `+2Hz` |
| **Money Glitch** | 거시경제 · 증시 · 재테크 | 직설적 월가 애널리스트 | `ko-KR-InJoonNeural` (남성) | `+12%` / `+0Hz` |
| **Secret Vault 24** | 기업 비사 · 경제 미스터리 | 중저음 다큐 내레이터 | `ko-KR-InJoonNeural` (남성) | `+10%` / `-2Hz` |
| **Dark Files Global** | 우주 · 심해 · 미스터리 사건 | 진중한 탐사 보도 앵커 | `ko-KR-HyunsuMultilingualNeural` (남성) | `+8%` / `-4Hz` |
| **Unseen Truth** | 역사 이면 · 숨겨진 진실 | 신뢰감 있는 스토리텔러 | `ko-KR-HyunsuMultilingualNeural` (남성) | `+10%` / `-2Hz` |
| **Brain Glitch** | 뇌과학 · 심리학 · 행동경제 | 명쾌한 심리 코치 | `ko-KR-SunHiNeural` (여성) | `+14%` / `+3Hz` |
| **Silent Signals** | 인간관계 · 비언어 심리 | 차분한 통찰형 아나운서 | `ko-KR-SunHiNeural` (여성) | `+13%` / `+2Hz` |
| **30Sec Shift** | 건강 · 수면 · 장수 의학 | 신뢰감 있는 메디컬 앵커 | `ko-KR-SunHiNeural` (여성) | `+14%` / `+2Hz` |
| **99% Missed** | 일상 상식 · 생산성 꿀팁 | 에너지 넘치는 트렌드 큐레이터 | `ko-KR-SunHiNeural` (여성) | `+15%` / `+3Hz` |
| **Why Nobody Tells** | 사회 구조 · 비즈니스 통찰 | 날카로운 이슈 브리퍼 | `ko-KR-SunHiNeural` (여성) | `+14%` / `+2Hz` |

### 3. 핵심 운영 시나리오 (User Journey)
1. **실시간 자율 수집 모드**: 백그라운드 데몬이 5분(사용자 설정 1~30분) 주기로 4개국 뉴스 RSS·HackerNews를 병렬 스캔하여 40개 순위 갱신.
2. **매일 08:00 완전 자동 편성**: 스케줄러가 매일 오전 8시 정각에 글로벌 종합 TOP 3 주제를 중복 체크 후 자동 영상 제작.
3. **수동 즉각 대응 모드**: 운영자가 대시보드에서 국가별 TOP 10 카드를 클릭해 원문 기사 및 평균 대비 조회수 예측 그래프를 확인한 뒤 `[이 근거로 AI 쇼츠 즉시 제작]` 클릭.
4. **3단 검수 및 안전 배포**: `[검수 대기]` 목록에서 제목·대본 수정 및 9:16 실물 영상 재생 후 `[최종 승인 및 업로드]` 클릭 시 YouTube Studio에 비공개(Private) 상태로 전송.
'@
[System.IO.File]::WriteAllText("$PWD\PROJECT_HANDOVER_MASTER.md", $doc1 + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "✅ 1/3 기획서 섹션 저장 완료" -ForegroundColor Green

\$doc2 = @'

---

## 제2부. 시스템 아키텍처 및 상세 설계 (System Design)

### 1. 전체 시스템 아키텍처 다이어그램
```text
┌─────────────────────────────────────────────────────────────────────────┐
│                    NEXUS STUDIO PRO (Frontend: index.html)               │
│  [KPI 모니터]  [4개국 TOP 10 레이더 & 근거 모달]  [3단 검수 워크스테이션] │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ REST API (JSON / MP4 Stream)
┌────────────────────────────────────▼────────────────────────────────────┐
│                  FastAPI 통합 백엔드 (api_server.py :8503)               │
│  ├─ Background Thread 1: auto_radar_and_scheduler_loop (수집 & 08:00 제작) │
│  ├─ Background Thread 2: watch_topics_loop (topics.txt 15초 원격 큐 감시) │
│  └─ BackgroundTasks: 단건 / 전 채널 일괄 / 모달 기반 비동기 렌더링 큐     │
└───┬─────────────────────────────┬──────────────────────────────┬────────┘
    │                             │                              │
    ▼                             ▼                              ▼
┌───────────────────┐   ┌───────────────────────┐   ┌─────────────────────┐
│  trend_radar.py   │   │    video_maker.py     │   │   yt_uploader.py    │
│ · Google News RSS │   │ · GPT-4o-mini 대본    │   │ · YouTube Data API  │
│ · BBC/NHK/SBS/HN  │   │ · Edge-TTS 신경망성우 │   │ · 채널별 OAuth Token│
│ · 정규식 HTML파싱 │   │ · DALL-E 3 / 그라데이션│   │ · Private 선업로드  │
│ · 바이럴 점수 산출│   │ · MoviePy 1080x1920   │   │                     │
└─────────┬─────────┘   └───────────┬───────────┘   └──────────┬──────────┘
          │                         │                          │
          └─────────────────────────▼──────────────────────────┘
                      ┌───────────────────────────┐
                      │ SQLite (data/studio_data) │
                      │ & Output MP4 (/output)    │
                      └───────────────────────────┘
```

### 2. SQLite 데이터베이스 스키마 설계 (`data/studio_data.db`)

#### ① `channels` (운영 채널 마스터)
* `id` (INTEGER PK): 채널 고유 번호
* `name` (TEXT): 채널명 (예: `Future Leak`)
* `platform` (TEXT): 플랫폼 구분 (`YouTube Shorts`)
* `persona` (TEXT): AI 대본 생성 시 주입할 톤앤매너 지시어

#### ② `trend_recommendations` (글로벌 트렌드 레이더 저장소)
* `id` (INTEGER PK): 트렌드 고유 ID
* `period_type` (TEXT): 편성 주기 구분 (`daily` | `weekly`)
* `region` (TEXT): 권역 코드 (`KR` | `US` | `JP` | `GB`)
* `rank_no` (INTEGER): 해당 국가 내 순위 (`1` ~ `10`)
* `is_global_top10` (INTEGER): 글로벌 종합 TOP 10 순위 (`1`~`10`, 미포함 시 `0`)
* `topic` (TEXT): 수집된 원문 뉴스 헤드라인
* `matched_channel` (TEXT): 키워드 매칭 엔진이 배정한 최적 채널명
* `source_name` / `source_url` (TEXT): 원천 언론사명 및 기사 직통 URL
* `est_views` / `avg_cat_views` (INTEGER): 추정 파급 조회수 및 동일 카테고리 평균 조회수
* `growth_pct` / `viral_score` (INTEGER): 평균 대비 급상승률(%) 및 바이럴 적합도 점수(`80`~`99`)
* `ai_reason` (TEXT): 채널 매칭 근거 요약 문구

#### ③ `pipeline_jobs` (영상 제작 및 검수 파이프라인)
* `id` (INTEGER PK): 작업 번호
* `channel_name` / `title` / `script` (TEXT): 채널명, 유튜브 제목, 6문장 내레이션 대본
* `video_path` (TEXT): 렌더링 완료된 로컬 MP4 경로 (`output/studio_YYYYMMDD_HHMMSS.mp4`)
* `stage` (TEXT): 작업 상태 (`Pending` 검수대기 / `Uploaded` 비공개 업로드 완료)
* `created_at` (TEXT): 생성 일시

#### ④ `auto_produced_topics` & `settings`
* `auto_produced_topics(topic PK, created_at)`: 매일 08:00 자동 제작 시 동일 주제 중복 렌더링 방지 이력 테이블.
* `settings(key PK, value)`: OpenAI API 키(`oa`) 등 시스템 환경 설정 저장소.

### 3. 핵심 알고리즘 및 렌더링 파이프라인 설계
1. **다국어 XML 인코딩 충돌 회피 수집기 (`trend_radar.py`)**:
   * 해외/국내 언론사 RSS의 `EUC-KR` / `UTF-8` 선언 불일치로 인한 `ElementTree` 파싱 실패를 원천 방지하기 위해 `r.content.decode('utf-8', errors='ignore')` 후 정규식(`<item>`, `<title>`, `<link>`)으로 제목과 원문 링크를 직접 추출함.
   * `ThreadPoolExecutor(max_workers=8)` 병렬 수집으로 4개국 40개 피드를 2~3초 내에 처리함.
2. **문장 단위 오디오-비디오 동기화 렌더링 (`video_maker.py`)**:
   * 대본을 6개 호흡 단위 문장으로 분할 → 문장별 `edge-tts` MP3 음성 생성 → `AudioFileClip`으로 정확한 발화 길이(`dur`) 측정 → `Pillow`로 상단 채널 배지·중앙 고대비 자막(후킹 첫 문장 노란색, 행동유도 마지막 문장 하늘색 강조)·하단 진행률 게이지 바가 합성된 `1080x1920` 프레임 생성 → 문장별 미세 줌인(`1.0 + idx * 0.018`) 효과 적용 후 `MoviePy`로 무손실(`yuv420p`, `libx264`, `aac`) 병합.
'@
[System.IO.File]::AppendAllText("$PWD\PROJECT_HANDOVER_MASTER.md", $doc2 + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "✅ 2/3 시스템 설계 섹션 저장 완료" -ForegroundColor Green


$doc3 = @'

---

## 제3부. 개발 명세 및 운영 매뉴얼 (Development & Operations)

### 1. 백엔드 REST API 명세 (`api_server.py`)

| Method | Endpoint | 요청 파라미터 / Body | 기능 및 응답 설명 |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | 없음 | 관제 포털 메인 화면(`index.html`) 반환 |
| `GET` | `/api/overview` | 없음 | 등록 채널 목록, 제작 작업 전체, `topics.txt` 큐 상태 반환 |
| `GET` | `/api/radar/{period}` | `period`: `daily` 또는 `weekly` | 4개국 40개 트렌드 및 종합 TOP 10 데이터 반환 (20건 미만 시 자동 스캔) |
| `POST` | `/api/radar/scan/{period}` | `period`: `daily` 또는 `weekly` | 외부 피드 즉시 재스캔 트리거 |
| `POST` | `/api/radar/auto-produce-now` | 없음 | 종합 TOP 10 중 미제작 상위 3개 주제 백그라운드 즉시 제작 |
| `POST` | `/api/radar/toggle-auto/{enabled}` | `enabled`: `1` 또는 `0` | 매일 08:00 자동 제작 스케줄러 ON/OFF 전환 |
| `POST` | `/api/radar/interval/{minutes}` | `minutes`: 정수(분) | 백그라운드 레이더 자동 수집 주기 변경 |
| `POST` | `/api/create` | `{"channel_name": str, "topic": str}` | 단건 영상 비동기 제작 요청 |
| `POST` | `/api/create-all` | 없음 | 등록된 10개 전 채널 일괄 제작 실행 |
| `PUT` | `/api/jobs/{job_id}` | `{"title": str, "script": str}` | 검수 워크스테이션에서 수정한 제목·대본 DB 저장 |
| `POST` | `/api/jobs/bulk-delete` | `{"job_ids": [int, ...]}` | 선택된 다수 작업 일괄 삭제 |
| `POST` | `/api/approve/{job_id}` | `job_id`: 정수 | 최종 승인 후 `yt_uploader.py` 호출하여 유튜브 비공개 업로드 |

### 2. 프론트엔드 설계 원칙 (`index.html`)
* **Zero-CDN 독립 아키텍처**: 외부 Tailwind CSS CDN 장애나 네트워크 지연 시에도 다크모드 대시보드 레이아웃이 무너지지 않도록 모든 스타일을 `<style>` 태그 내 순수 CSS Grid/Flexbox로 자체 내장함.
* **실시간 스캔 피드백**: `[↻ 즉시 재스캔]` 클릭 시 CSS `@keyframes spin360` 회전 스피너 애니메이션과 버튼 잠금(`disabled`)을 적용하여 수집 진행 상태를 직관적으로 표시.

### 3. 개발 및 운영 시 필수 준수 사항 (트러블슈팅 기록)
1. **Docker 컨테이너 파일 동기화**:
   * 현재 컨테이너(`nexus_shorts_center`)는 로컬 폴더와 실시간 볼륨 마운트가 분리되어 있으므로, 로컬에서 `.py` 또는 `.html` 수정 후 반드시 `docker cp <파일명> nexus_shorts_center:/app/<파일명>` 명령으로 컨테이너 내부에 복사해야 반영됨.
2. **Windows PowerShell UTF-8 인코딩 보호**:
   * PowerShell 파이프(`|`)로 한글 문자열을 컨테이너에 직접 전달하면 CP949 변환으로 인해 `????` 깨짐이 발생함. 반드시 `[System.IO.File]::WriteAllText(..., [System.Text.UTF8Encoding]::new($false))`로 로컬 저장 후 `docker cp`를 사용할 것.
3. **API 키 및 채널 관리 명령어**:
   * **OpenAI API 키 설정** (미설정 시 내장 템플릿 대본 및 그라데이션 시네마틱 배경으로 자동 폴백 작동):
     ```powershell
     docker exec nexus_shorts_center python -c "import sqlite3; c=sqlite3.connect('data/studio_data.db'); c.execute(\"INSERT OR REPLACE INTO settings VALUES ('oa', 'sk-여기에키입력')\"); c.commit()"
     ```
   * **8503 서버 강제 재기동**:
     ```powershell
     docker exec nexus_shorts_center bash -c "pkill -9 -f uvicorn || true"
     docker exec -d nexus_shorts_center uvicorn api_server:app --host 0.0.0.0 --port 8503
     ```
'@
[System.IO.File]::AppendAllText("$PWD\PROJECT_HANDOVER_MASTER.md", $doc3 + "`n", [System.Text.UTF8Encoding]::new($false))
Write-Host "✅ 3/3 전체 기획·설계·개발 인수인계서(PROJECT_HANDOVER_MASTER.md) 생성 완료!" -ForegroundColor Green

