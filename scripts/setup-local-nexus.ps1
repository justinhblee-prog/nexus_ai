[CmdletBinding()]
param(
    [switch]$Start
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$EnvPath = Join-Path $RepoRoot ".env"

$Lines = [System.Collections.Generic.List[string]]::new()
if (Test-Path $EnvPath) {
    foreach ($Line in (Get-Content -Path $EnvPath -Encoding utf8)) {
        $Lines.Add($Line)
    }
}

$Values = @{}
foreach ($Line in $Lines) {
    if ($Line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $Key = $Matches[1]
        $Value = $Matches[2].Trim()
        if (($Value.StartsWith('"') -and $Value.EndsWith('"')) -or ($Value.StartsWith("'") -and $Value.EndsWith("'"))) {
            $Value = $Value.Substring(1, $Value.Length - 2)
        }
        $Values[$Key] = $Value
    }
}

if (-not $Values.ContainsKey("NEXUS_API_PASSWORD") -or [string]::IsNullOrWhiteSpace($Values["NEXUS_API_PASSWORD"])) {
    Write-Host "FastAPI/Streamlit 공통 운영자 비밀번호를 설정합니다. 값은 화면에 표시되지 않습니다."
    $SecurePassword = Read-Host "운영자 비밀번호 (12자 이상, 영문/숫자/._~- 권장)" -AsSecureString
    $PasswordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecurePassword)
    try {
        $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($PasswordPointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($PasswordPointer)
    }
    if ($Password.Length -lt 12 -or $Password -notmatch '^[A-Za-z0-9._~-]+$') {
        throw "비밀번호는 12자 이상이어야 하며 영문, 숫자, ., _, ~, -만 사용할 수 있습니다. .env는 변경하지 않았습니다."
    }
    $Lines.Add("NEXUS_API_PASSWORD=$Password")
    $Values["NEXUS_API_PASSWORD"] = $Password
    $Password = $null
}

if ($Values.ContainsKey("NEXUS_API_PASSWORD") -and $Values["NEXUS_API_PASSWORD"].Length -lt 12) {
    throw "기존 NEXUS_API_PASSWORD가 12자보다 짧습니다. .env에서 안전한 비밀번호로 변경해 주세요."
}

if (-not $Values.ContainsKey("NEXUS_SESSION_SECRET") -or $Values["NEXUS_SESSION_SECRET"].Length -lt 32) {
    $Secret = & python -c "import secrets; print(secrets.token_urlsafe(48))"
    if ($LASTEXITCODE -ne 0 -or $Secret.Length -lt 32) {
        throw "Python secrets 모듈로 세션 키를 생성하지 못했습니다."
    }
    $SecretLineFound = $false
    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match '^\s*NEXUS_SESSION_SECRET=') {
            $Lines[$Index] = "NEXUS_SESSION_SECRET=$Secret"
            $SecretLineFound = $true
            break
        }
    }
    if (-not $SecretLineFound) {
        $Lines.Add("NEXUS_SESSION_SECRET=$Secret")
    }
    $Values["NEXUS_SESSION_SECRET"] = $Secret
    $Secret = $null
}

if ($Values.ContainsKey("NEXUS_AUTH_ENABLED") -and $Values["NEXUS_AUTH_ENABLED"].ToLowerInvariant() -in @("0", "false", "no", "off")) {
    throw "NEXUS_AUTH_ENABLED=false 설정이 발견됐습니다. 안전한 기본값은 true입니다. .env를 확인한 뒤 명시적으로 수정해 주세요."
}
if (-not $Values.ContainsKey("NEXUS_AUTH_ENABLED") -or [string]::IsNullOrWhiteSpace($Values["NEXUS_AUTH_ENABLED"])) {
    $AuthLineFound = $false
    for ($Index = 0; $Index -lt $Lines.Count; $Index++) {
        if ($Lines[$Index] -match '^\s*NEXUS_AUTH_ENABLED=') {
            $Lines[$Index] = "NEXUS_AUTH_ENABLED=true"
            $AuthLineFound = $true
            break
        }
    }
    if (-not $AuthLineFound) {
        $Lines.Add("NEXUS_AUTH_ENABLED=true")
    }
    $Values["NEXUS_AUTH_ENABLED"] = "true"
}
if (-not $Values.ContainsKey("NEXUS_COOKIE_SECURE")) {
    $Lines.Add("NEXUS_COOKIE_SECURE=false")
}
if (-not $Values.ContainsKey("NEXUS_STREAMLIT_HOST_PORT")) {
    $Lines.Add("NEXUS_STREAMLIT_HOST_PORT=28502")
    $Values["NEXUS_STREAMLIT_HOST_PORT"] = "28502"
}
if (-not $Values.ContainsKey("NEXUS_API_HOST_PORT")) {
    $Lines.Add("NEXUS_API_HOST_PORT=28503")
    $Values["NEXUS_API_HOST_PORT"] = "28503"
}

Set-Content -Path $EnvPath -Value $Lines -Encoding utf8NoBOM
Write-Host ".env 필수 설정을 확인했습니다. 비밀값은 출력하지 않았습니다."

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose 설정 검증에 실패했습니다. .env와 docker-compose.yml을 확인해 주세요."
}
Write-Host "Docker Compose 설정 검증: PASS"

if ($Start) {
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "컨테이너 시작에 실패했습니다. 기존 컨테이너/볼륨은 삭제하지 않았습니다."
    }

    $ApiPort = [string]$Values["NEXUS_API_HOST_PORT"]
    $ApiUrl = "http://127.0.0.1:$ApiPort"
    $Ready = $false
    for ($Attempt = 1; $Attempt -le 45; $Attempt++) {
        try {
            $Session = Invoke-RestMethod -Uri "$ApiUrl/api/session/status" -TimeoutSec 3
            if ($Session.required -eq $true -and $Session.configured -eq $true) {
                $Ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
        Start-Sleep -Seconds 1
    }
    if (-not $Ready) {
        docker compose ps
        docker compose logs --tail=80 shorts-center
        throw "FastAPI 인증 설정 확인에 실패했습니다. 컨테이너와 비밀값을 확인해 주세요."
    }

    Write-Host "FastAPI 인증 상태: PASS (인증 필수 / 비밀값 설정 완료)"
    docker compose ps
    Write-Host "Browser Studio: $ApiUrl"
    Write-Host "Streamlit Studio: http://127.0.0.1:$([string]$Values["NEXUS_STREAMLIT_HOST_PORT"])"
    Write-Host "브라우저에서 운영자 비밀번호로 로그인해 주세요."
}
else {
    Write-Host "설정만 완료했습니다. 시작하려면 다음 명령을 실행하세요: docker compose up -d --build"
}
