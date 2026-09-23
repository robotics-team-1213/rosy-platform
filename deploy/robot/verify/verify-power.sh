#!/usr/bin/env bash
set -Eeuo pipefail

# PWR-005 벤치 검증 — 절전 모드와 LiDAR 듀티를 실기에서 확인한다.
# 읽기 전용 점검은 항상 실행하고, 모드를 강제하는 제어 점검은
# ROSY_API_TOKEN(operator 이상)이 있을 때만 실행한다.

API="${ROSY_API:-http://127.0.0.1:8080}"
TOKEN="${ROSY_API_TOKEN:-}"
CONFIG_FILE="${ROSY_CONFIG_FILE:-/etc/rosy/rosy.yaml}"
SCAN_TOPIC="${ROSY_SCAN_TOPIC:-/scan}"
SAMPLE_CSV="${ROSY_POWER_CSV:-}"
SCAN_WINDOW="${ROSY_SCAN_WINDOW:-5}"
SETTLE_S="${ROSY_SETTLE_S:-3}"

failures=0

usage() {
  cat <<'EOF'
Usage: verify-power.sh [--csv PATH]

PWR-005 절전/LiDAR 듀티 벤치 검증. 읽기 전용 점검(플랫폼 전력 상태, EEPROM,
API 계약, 설정, LiDAR 서비스, 기준 스캔 주기)은 항상 실행한다.

ROSY_API_TOKEN 이 설정되면 제어 점검까지 실행한다: STANDBY 강제 → LiDAR 정지
확인 → 스캔 무음 확인 → 웨이크 후 첫 유효 스캔까지의 실측 지연을 설정된
spinup_s 와 비교한다.

--csv PATH 를 주면 모드별 배터리 전압 표본을 CSV로 남긴다. 외부 전류계 측정치와
맞춰 보기 위한 것으로, 전류 자체는 이 스크립트가 측정하지 않는다.

환경변수: ROSY_API, ROSY_API_TOKEN, ROSY_CONFIG_FILE, ROSY_SCAN_TOPIC,
          ROSY_SCAN_WINDOW, ROSY_SETTLE_S
EOF
}

while (($# > 0)); do
  case "$1" in
    --csv)
      shift
      [[ $# -gt 0 ]] || { echo "--csv requires a path" >&2; exit 2; }
      SAMPLE_CSV="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

pass() {
  printf 'PASS  %-10s %s\n' "$1" "$2"
}

warn() {
  printf 'WARN  %-10s %s\n' "$1" "$2"
}

fail() {
  printf 'FAIL  %-10s %s\n' "$1" "$2"
  failures=$((failures + 1))
}

note() {
  printf 'NOTE  %-10s %s\n' "$1" "$2"
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

api_get() {
  curl -fsS --max-time 5 -H "Authorization: Bearer $TOKEN" "$API$1" 2>/dev/null
}

api_post() {
  curl -fsS --max-time 5 -X POST -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' ${2:+-d "$2"} "$API$1" 2>/dev/null
}

# JSON 한 필드를 뽑는다. jq가 없는 Pi OS Lite를 전제로 python3만 쓴다.
json_field() {
  python3 -c '
import json, sys
data = json.load(sys.stdin)
for key in sys.argv[1].split("."):
    data = data[key]
print(data)
' "$1" 2>/dev/null
}

# --- 1. 플랫폼 전력 상태 (D-25 근거 실측) -----------------------------------

if [[ -r /sys/power/state ]]; then
  states="$(tr -d '\n' </sys/power/state)"
  note "PLATFORM" "/sys/power/state = '$states'"
  if grep -qw disk /sys/power/state; then
    warn "PLATFORM" "하이버네이트(disk)가 보고된다 — D-25 전제를 재검토할 것"
  elif grep -qw mem /sys/power/state; then
    warn "PLATFORM" "suspend(mem)이 보고된다 — D-25 전제를 재검토할 것"
  else
    pass "PLATFORM" "suspend/hibernate 미지원 — D-25 전제와 일치"
  fi
else
  warn "PLATFORM" "/sys/power/state 를 읽을 수 없다"
fi

if has_command rpi-eeprom-config; then
  eeprom="$(rpi-eeprom-config 2>/dev/null || true)"
  halt_cfg="$(printf '%s\n' "$eeprom" | grep -E '^POWER_OFF_ON_HALT=' || true)"
  note "EEPROM" "${halt_cfg:-POWER_OFF_ON_HALT 미설정 (기본값)}"
else
  note "EEPROM" "rpi-eeprom-config 없음 — Pi 5가 아니거나 도구 미설치"
fi

# --- 2. API 계약 -------------------------------------------------------------

if ! has_command curl; then
  fail "API" "curl 이 없어 API 점검을 할 수 없다"
elif [[ -z "$TOKEN" ]]; then
  warn "API" "ROSY_API_TOKEN 미설정 — 읽기/제어 점검을 건너뛴다"
else
  power_json="$(api_get /api/v1/power || true)"
  if [[ -z "$power_json" ]]; then
    fail "API" "$API/api/v1/power 가 응답하지 않는다 (토큰/런타임 확인)"
  else
    mode="$(printf '%s' "$power_json" | json_field mode || true)"
    spinning="$(printf '%s' "$power_json" | json_field lidar_spinning || true)"
    ready="$(printf '%s' "$power_json" | json_field lidar_ready || true)"
    if [[ -z "$mode" || -z "$spinning" || -z "$ready" ]]; then
      fail "API" "power 응답에 mode/lidar_spinning/lidar_ready 가 없다: $power_json"
    else
      pass "API" "mode=$mode lidar_spinning=$spinning lidar_ready=$ready"
    fi
  fi
fi

# --- 3. 설정값 ---------------------------------------------------------------

standby_stop=""
spinup_s=""
if [[ -r "$CONFIG_FILE" ]]; then
  # 성공하면 "OK <standby_stop> <spinup_s>", 아니면 "ERR <사유>" 를 낸다.
  # 사유를 구분해야 "설정이 없다"와 "파서가 없다"를 혼동하지 않는다.
  config_probe="$(python3 - "$CONFIG_FILE" <<'PY'
import sys
try:
    import yaml
except ImportError:
    print("ERR pyyaml-missing")
    raise SystemExit(0)
try:
    cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception as exc:                       # 손상된 YAML도 사유로 남긴다
    print("ERR parse-failed:%s" % type(exc).__name__)
    raise SystemExit(0)
lidar = ((cfg.get("power") or {}).get("lidar") or {})
if not lidar:
    print("ERR no-power-lidar-block")
else:
    print("OK", str(lidar.get("standby_stop", False)).lower(),
          lidar.get("spinup_s", 2.0))
PY
)" || config_probe="ERR probe-failed"

  case "$config_probe" in
    OK\ *)
      read -r _ standby_stop spinup_s <<<"$config_probe"
      note "CONFIG" "standby_stop=$standby_stop spinup_s=$spinup_s ($CONFIG_FILE)"
      ;;
    "ERR pyyaml-missing")
      warn "CONFIG" "python3 yaml 모듈이 없다 — core 컨테이너 안에서 실행하거나 python3-yaml 설치"
      ;;
    "ERR no-power-lidar-block")
      warn "CONFIG" "$CONFIG_FILE 에 power.lidar 블록이 없다 — 기본값(standby_stop=false)이 적용된다"
      ;;
    *)
      warn "CONFIG" "$CONFIG_FILE 을 해석하지 못했다 ($config_probe)"
      ;;
  esac
else
  warn "CONFIG" "$CONFIG_FILE 를 읽을 수 없다"
fi

# --- 4. LiDAR 서비스 ---------------------------------------------------------

if ! has_command ros2; then
  warn "LIDARSVC" "ros2 CLI 가 없다 — 컨테이너 안에서 실행할 것"
else
  services="$(ros2 service list 2>/dev/null || true)"
  if printf '%s\n' "$services" | grep -q 'stop_motor' &&
     printf '%s\n' "$services" | grep -q 'start_motor'; then
    pass "LIDARSVC" "start_motor / stop_motor 서비스가 보인다"
  else
    fail "LIDARSVC" "start_motor/stop_motor 가 없다 — sllidar 드라이버 미기동"
  fi
fi

# 지정 시간 동안 스캔 메시지를 세어 초당 주기를 돌려준다.
scan_rate() {
  local window="$1"
  timeout "$((window + 3))" ros2 topic hz "$SCAN_TOPIC" --window 10 2>/dev/null |
    grep -m1 -oE 'average rate: [0-9.]+' | grep -oE '[0-9.]+' || true
}

record_sample() {
  [[ -n "$SAMPLE_CSV" ]] || return 0
  local label="$1" rate="$2" voltage=""
  if [[ -n "$TOKEN" ]]; then
    voltage="$(api_get /api/v1/robot/state |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["battery"].get("voltage",""))' 2>/dev/null || true)"
  fi
  printf '%s,%s,%s,%s\n' "$(date -Is)" "$label" "${rate:-}" "${voltage:-}" >>"$SAMPLE_CSV"
}

if [[ -n "$SAMPLE_CSV" && ! -s "$SAMPLE_CSV" ]]; then
  printf 'timestamp,label,scan_hz,battery_voltage\n' >"$SAMPLE_CSV"
  note "CSV" "표본을 $SAMPLE_CSV 에 기록한다 (전류는 외부 계측기 몫)"
fi

# --- 5. 제어 점검 (토큰 필요) ------------------------------------------------

if [[ -z "$TOKEN" ]]; then
  warn "CONTROL" "ROSY_API_TOKEN 미설정 — STANDBY/스핀업 실측을 건너뛴다"
elif ! has_command ros2; then
  warn "CONTROL" "ros2 CLI 가 없어 스캔 기반 실측을 건너뛴다"
elif [[ "$standby_stop" != "true" ]]; then
  warn "CONTROL" "standby_stop=false — LiDAR 정지 경로가 비활성이라 실측 대상이 아니다"
  note "CONTROL" "실측하려면 power.lidar.standby_stop 을 true 로 두고 다시 실행할 것"
elif [[ "$(api_get /api/v1/robot/state | json_field mode || true)" != "IDLE" ]]; then
  # 로봇 모드가 IDLE이 아니면 PowerManager가 ACTIVE를 고정하므로 STANDBY 강제가
  # 조용히 무시된다. PWR-005 결함으로 오진하지 않도록 여기서 걸러낸다.
  warn "CONTROL" "로봇 모드가 IDLE이 아니다 — 절전 인터록이 ACTIVE를 고정하므로 실측 불가"
  note "CONTROL" "로봇을 IDLE로 두고(내비게이션·수동주행 종료, E-Stop 해제) 다시 실행할 것"
else
  api_post /api/v1/power/wake >/dev/null || true
  sleep "$SETTLE_S"
  active_rate="$(scan_rate "$SCAN_WINDOW")"
  if [[ -z "$active_rate" ]]; then
    fail "SCANBASE" "ACTIVE 에서 $SCAN_TOPIC 주기를 측정하지 못했다"
  else
    pass "SCANBASE" "ACTIVE 스캔 주기 ${active_rate} Hz"
    record_sample ACTIVE "$active_rate"
  fi

  if ! api_post /api/v1/power/mode '{"mode":"STANDBY"}' >/dev/null; then
    fail "STANDBY" "STANDBY 강제 요청이 실패했다"
  else
    sleep "$SETTLE_S"
    after="$(api_get /api/v1/power || true)"
    mode_now="$(printf '%s' "$after" | json_field mode || true)"
    spin_now="$(printf '%s' "$after" | json_field lidar_spinning || true)"
    if [[ "$mode_now" == "STANDBY" && "$spin_now" == "False" ]]; then
      pass "STANDBY" "STANDBY 진입, lidar_spinning=False"
    else
      fail "STANDBY" "기대: STANDBY/False, 실제: $mode_now/$spin_now"
    fi

    standby_rate="$(scan_rate "$SCAN_WINDOW")"
    if [[ -z "$standby_rate" ]]; then
      pass "QUIET" "STANDBY 에서 스캔이 멈췄다 (주기 측정 불가 = 기대 동작)"
    else
      fail "QUIET" "STANDBY 인데 스캔이 ${standby_rate} Hz 로 계속된다"
    fi
    record_sample STANDBY "${standby_rate:-0}"

    # 웨이크 → 첫 스캔까지의 실측 지연. spinup_s 추정치의 근거가 된다.
    started="$(date +%s.%N)"
    api_post /api/v1/power/wake >/dev/null || true
    if timeout 30 ros2 topic echo --once "$SCAN_TOPIC" >/dev/null 2>&1; then
      ended="$(date +%s.%N)"
      measured="$(python3 -c "print('%.2f' % (float('$ended') - float('$started')))")"
      note "SPINUP" "웨이크 → 첫 스캔 실측 ${measured}s (설정 spinup_s=${spinup_s:-?})"
      over="$(python3 -c "print('1' if float('$measured') > float('${spinup_s:-2.0}') else '0')")"
      if [[ "$over" == "1" ]]; then
        fail "SPINUP" "실측이 spinup_s 를 넘는다 — lidar_ready 가 너무 일찍 참이 된다"
      else
        pass "SPINUP" "실측 ${measured}s <= spinup_s ${spinup_s:-2.0}s"
      fi
    else
      fail "SPINUP" "웨이크 후 30s 안에 스캔이 돌아오지 않았다"
    fi
  fi
fi

# --- 6. Nav2 관찰 ------------------------------------------------------------

if has_command ros2; then
  nav_nodes="$(ros2 node list 2>/dev/null | grep -cE 'controller_server|planner_server' || true)"
  if [[ "${nav_nodes:-0}" -gt 0 ]]; then
    note "NAV2" "Nav2 노드 ${nav_nodes}개 활성 — 스캔 단절 구간의 코스트맵/복구 로그를 확인할 것"
  else
    note "NAV2" "Nav2 비활성 — 스캔 단절 영향은 별도 세션에서 관찰해야 한다"
  fi
fi

echo
if ((failures > 0)); then
  echo "verify-power: ${failures}건 실패"
  exit 1
fi
echo "verify-power: 실패 없음"
echo "전류 측정은 이 스크립트 밖이다 — docs/deployment/power-bench-verification.md 를 따를 것"
