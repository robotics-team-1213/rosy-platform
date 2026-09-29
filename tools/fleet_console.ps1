# 관제타워 Fleet 콘솔 실행 스크립트 (Windows / 관제실 PC)
#
# 쓰는 법:
#   powershell -ExecutionPolicy Bypass -File tools\fleet_console.ps1
#
# - 관제 UI: http://<이 PC의 LAN IP>:8090/console
# - 외부(루프백 밖) 접속이므로 --token 이 필수다 (cli.run_console 이 강제).
#   접속 시 요청 헤더: Authorization: Bearer <FLEET_CONSOLE_TOKEN>
#   (브라우저는 console.js 가 토큰을 물어본다 — 프롬프트에 같은 값을 넣는다)
#
# robots.yaml 은 운영자 토큰 평문 파일이다. 이 스크립트는 로컬 전용
# 경로(%LOCALAPPDATA%\rosy\robots.yaml)를 먼저 보고, 없으면 예시를 만들어 준다.
# 절대 저장소에 커밋하지 않는다.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot   # 저장소 루트 (Rosy OS)

# ── 1. robots.yaml 위치 (로컬 전용, 커밋 금지) ─────────────────────────
$robots = Join-Path $env:LOCALAPPDATA "rosy\robots.yaml"
if (-not (Test-Path $robots)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $robots) | Out-Null
    @"
robots:
  - robot_id: "rosy_01"
    base_url: "http://<ROBOT-1-IP>:8080"
    token: "<ROBOT-1-OPERATOR-TOKEN>"
  - robot_id: "rosy_02"
    base_url: "http://<ROBOT-2-IP>:8080"
    token: "<ROBOT-2-OPERATOR-TOKEN>"
"@ | Set-Content -Path $robots -Encoding UTF8
    Write-Host "robots.yaml 뼈대를 만들었다: $robots"
    Write-Host "  → 로봇 IP 와 operator 토큰을 채운 뒤 다시 실행한다."
    notepad $robots
    exit 1
}

# ── 2. 관제 토큰 (환경변수 우선, 없으면 로컬 파일에서) ─────────────────
$token = $env:FLEET_CONSOLE_TOKEN
$tokenFile = Join-Path $env:LOCALAPPDATA "rosy\console_token.txt"
if (-not $token) {
    if (Test-Path $tokenFile) {
        $token = (Get-Content $tokenFile -Raw).Trim()
    } else {
        $token = [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
        Set-Content -Path $tokenFile -Value $token -Encoding ASCII
        Write-Host "관제 토큰을 새로 만들었다: $tokenFile"
    }
}

# ── 3. 설치 가능한 공용 L1 웹 자산 (D-129, D-157) ────────────────────
$webCommon = Join-Path $repo "src\core\web_common"

# ── 4. 서버 기동 — 0.0.0.0 바인드 + 토큰 필수 ─────────────────────────
# 로봇(pinky) → 타워는 아웃바운드라 방화벽 규칙이 필요 없다. 로봇을 향해
# 열려 있는 것도 없다 — gather/scatter는 전부 타워에서 로봇으로 나간다.
# 방화벽 인바운드가 필요한 유일한 경우는 "타워 말고 다른 기기(폰·태블릿)의
# 브라우저에서 이 UI를 열 때"다. 그때 관리자가 한 번:
#   New-NetFirewallRule -DisplayName "ROSY Fleet Console" -Direction Inbound `
#       -LocalPort 8090 -Protocol TCP -Action Allow -Profile Private
# 타워 자신의 브라우저(127.0.0.1)는 규칙 없이도 된다.
$env:PYTHONPATH = @(
    (Join-Path $repo "src\site\fleet"),
    (Join-Path $repo "src\core\core_common"),
    (Join-Path $repo "src\core\core_features")
) -join ";"

Write-Host "fleet console: http://127.0.0.1:8090/console  (token required)"
python -m fleet.cli console --robots $robots --host 0.0.0.0 --port 8090 --web-common $webCommon --token $token
