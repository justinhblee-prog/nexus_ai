[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine에 연결할 수 없습니다."
}

docker compose ps
$EnvValues = @{}
if (Test-Path ".env") {
    foreach ($Line in (Get-Content ".env" -Encoding utf8)) {
        if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $EnvValues[$Matches[1]] = $Matches[2].Trim()
        }
    }
}
$ApiPort = if ($EnvValues.ContainsKey("NEXUS_API_HOST_PORT")) { $EnvValues["NEXUS_API_HOST_PORT"] } else { "28503" }
$StreamlitPort = if ($EnvValues.ContainsKey("NEXUS_STREAMLIT_HOST_PORT")) { $EnvValues["NEXUS_STREAMLIT_HOST_PORT"] } else { "28502" }
$ApiUrl = "http://127.0.0.1:$ApiPort"
$StreamlitUrl = "http://127.0.0.1:$StreamlitPort"

$Session = Invoke-RestMethod -Uri "$ApiUrl/api/session/status" -TimeoutSec 5
if ($Session.required -ne $true -or $Session.configured -ne $true) {
    throw "FastAPI 인증이 필수/설정 상태가 아닙니다."
}
Write-Host "PASS: FastAPI session configuration (required=true, configured=true)"

$UnauthenticatedApi = Invoke-WebRequest -Uri "$ApiUrl/api/overview" -SkipHttpErrorCheck -TimeoutSec 5
if ($UnauthenticatedApi.StatusCode -ne 401) {
    throw "비인증 /api/overview 요청이 401이 아닙니다: $($UnauthenticatedApi.StatusCode)"
}
Write-Host "PASS: unauthenticated API request rejected (401)"

$UnauthenticatedMedia = Invoke-WebRequest -Uri "$ApiUrl/output/session-guard-check.mp4" -SkipHttpErrorCheck -TimeoutSec 5
if ($UnauthenticatedMedia.StatusCode -ne 401) {
    throw "비인증 /output 미디어 요청이 401이 아닙니다: $($UnauthenticatedMedia.StatusCode)"
}
Write-Host "PASS: unauthenticated media request rejected (401)"

$StreamlitHealth = Invoke-WebRequest -Uri "$StreamlitUrl/_stcore/health" -TimeoutSec 5
if ($StreamlitHealth.StatusCode -ne 200) {
    throw "Streamlit health endpoint가 정상 응답하지 않습니다."
}
Write-Host "PASS: Streamlit health endpoint"

docker compose exec -T shorts-center python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    throw "컨테이너 내 단위 테스트가 실패했습니다."
}
docker compose exec -T shorts-center python -m unittest discover -s integration_tests -p "test_video_render_integration.py" -v
if ($LASTEXITCODE -ne 0) {
    throw "컨테이너 내 실제 MP4 렌더링 통합 테스트가 실패했습니다."
}

Write-Host "실시간 RSS/Hacker News 연결 상태를 조회합니다 (읽기 전용, DB 변경 없음)."
docker compose exec -T shorts-center python scripts/check-feed-connectivity.py
if ($LASTEXITCODE -ne 0) {
    Write-Warning "일부 외부 피드가 응답하지 않습니다. 위 소스별 진단을 확인하세요. API/렌더링 검증 결과와는 별개입니다."
}

docker compose ps
Write-Host "로컬 런타임 검증: PASS"
Write-Host "브라우저 로그인과 실제 Google/YouTube OAuth·Private 업로드는 별도 운영자 계정 확인이 필요합니다."
