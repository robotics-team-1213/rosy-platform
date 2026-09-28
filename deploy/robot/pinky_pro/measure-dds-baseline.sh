#!/usr/bin/env bash
# measure-dds-baseline.sh — Phase 0 베이스라인 계측 (ROSY-PLN, ADR D-34)
#
# 사용: sudo ./measure-dds-baseline.sh [출력경로]
#   기본 출력: /var/lib/rosy/dds-baseline-<타임스탬프>.md
#
# 이 스크립트가 존재하는 이유: 발행 주기를 바꾸기 전과 후를 같은 방법으로 재야
# 하는데, 손으로 열 몇 개 토픽을 돌리면 창마다 조건이 달라진다. 특히 아래 세
# 함정은 손으로 재면 거의 반드시 밟는다.
#
# 함정 1 — 구독자가 없으면 Nav2 는 아예 발행하지 않는다.
#   nav2_costmap_2d 의 Costmap2DPublisher::publishCostmap() 은 토픽마다
#   `get_subscription_count() > 0` 을 확인하고 나서야 prepareGrid()/prepareCostmap()
#   을 돌린다. 즉 `ros2 topic bw` 를 붙이는 행위 자체가 구독자를 만들어
#   측정 대상 트래픽을 발생시킨다. 붙이기 전 구독자 수를 함께 적어야 그 수치가
#   "원래 흐르던 양"인지 "내가 켠 양"인지 구분된다.
#
# 함정 2 — `ros2 topic bw` 는 기본 RELIABLE 로 구독한다.
#   BEST_EFFORT 퍼블리셔에는 붙지 않아 0 이 나온다. 0 은 승리가 아니라 실패한
#   측정이다. 그래서 0 이 나오면 이 스크립트는 UNMATCHED 로 표시한다.
#
# 함정 3 — latched(TRANSIENT_LOCAL) 토픽은 첫 샘플 뒤 0 으로 읽힌다.
#   `map` 이 그렇다. 0 을 트래픽 없음으로 읽으면 안 된다.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROSY_ENV_FILE:-$SCRIPT_DIR/.env}"
OUT="${1:-/var/lib/rosy/dds-baseline-$(date -u +%Y%m%dT%H%M%SZ).md}"

# 측정 창. 코스트맵이 0.2 Hz 면 한 장 잡는 데만 5초가 걸리므로 짧게 잡으면
# 표본이 0 개인 채로 0 KB/s 가 나온다.
BW_WINDOW="${ROSY_BW_WINDOW:-30}"
CPU_WINDOW="${ROSY_CPU_WINDOW:-60}"
IDLE_REPEATS="${ROSY_IDLE_REPEATS:-3}"

fail() { echo "FAIL: $*" >&2; exit 1; }
note() { echo "  $*" >&2; }

# --- 전제 확인 -------------------------------------------------------------

[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"
cd "$SCRIPT_DIR"

MODE="$(sed -n 's/^ROSY_RUNTIME_MODE=//p' "$ENV_FILE" | tail -n 1)"
MODE="${MODE%$'\r'}"
NS="$(sed -n 's/^ROSY_NAMESPACE=//p' "$ENV_FILE" | tail -n 1)"
NS="${NS%$'\r'}"
DOMAIN="$(sed -n 's/^ROS_DOMAIN_ID=//p' "$ENV_FILE" | tail -n 1)"
DOMAIN="${DOMAIN%$'\r'}"

[[ -n "$NS" ]] || fail "ROSY_NAMESPACE is unset in $ENV_FILE (ADR D-33)"
[[ -n "$DOMAIN" ]] || fail "ROS_DOMAIN_ID is unset in $ENV_FILE (ADR D-33)"

# 절대 이름으로 만드는 것은 비어 있는지 확인한 *뒤*다. 앞에서 하면
# 미설정 네임스페이스가 "/" 가 되어 위 게이트를 그냥 통과한다.
NS="/${NS#/}"

# 기본 배포는 core 전용이라 Nav2 가 아예 없고 코스트맵 토픽도 존재하지 않는다.
# 여기서 막지 않으면 "모든 토픽 0 KB/s" 라는 그럴듯한 거짓 보고서가 나온다.
[[ "$MODE" == "hardware" ]] || fail "ROSY_RUNTIME_MODE=$MODE — Phase 0 은 hardware 모드에서만 의미가 있다 (core/motor 에는 Nav2 도 코스트맵도 없다)"

DC=(docker compose --env-file "$ENV_FILE" --profile hardware)
# PYTHONUNBUFFERED 가 없으면 이 스크립트는 조용히 아무것도 재지 못한다.
# `exec -T` 는 TTY 를 주지 않으므로 stdout 이 파이프가 되고, Python 은 블록
# 버퍼링(4KB)으로 넘어간다. 30초짜리 bw 출력은 2KB 남짓이라 한 번도 flush 되지
# 않고, timeout 의 시그널이 그대로 프로세스를 죽여 출력이 0 바이트가 된다.
# 그러면 모든 칸이 UNMATCHED 로 찍히고 리포트는 쓸모가 없다.
EX=("${DC[@]}" exec -T -e PYTHONUNBUFFERED=1 rosy-io)

"${DC[@]}" ps -q rosy-io >/dev/null 2>&1 || fail "rosy-io is not running; start it with runtime-mode.sh up"

# 컨테이너는 read_only + cap_drop ALL 이고 HOME 도 쓸 수 없다. 두 번째 ros2 CLI
# 가 그 안에서 뜨는지는 실제로 해봐야 안다.
note "rig sanity: ros2 topic bw"
"${EX[@]}" ros2 topic bw --help >/dev/null 2>&1 || fail "ros2 topic bw is unavailable inside rosy-io"
HAS_TOP=yes
"${EX[@]}" sh -c 'command -v top' >/dev/null 2>&1 || HAS_TOP=no

# --- 측정 대상 -------------------------------------------------------------
# 코스트맵은 네 개 모두 잰다. `costmap` 과 `costmap_raw` 는 같은 격자를 서로 다른
# 타입으로 내보내며, 상류 소스상 같은 publishCostmap() 호출에서 함께 나간다.
TOPICS=(
  "$NS/global_costmap/costmap"
  "$NS/global_costmap/costmap_raw"
  "$NS/local_costmap/costmap"
  "$NS/local_costmap/costmap_raw"
  "$NS/local_costmap/voxel_grid"
  "$NS/particle_cloud"
  "$NS/plan"
  "$NS/scan"
  "$NS/odom"
  # D-169: imu_bno055 is bench-only in the v1 product runtime — this entry
  # measures 0/no-device unless the bench IMU node was started separately.
  "$NS/imu_raw"
  "$NS/us_sensor/range"
  "$NS/batt_state"
  "$NS/cmd_vel"
  "$NS/map"
  "/tf"
  "/tf_static"
)

# 조용한 십수 분은 멈춘 것처럼 보인다. 실제로 그만큼 걸리므로 미리 말해 둔다.
note "measuring ${#TOPICS[@]} topics x 2 windows x ${BW_WINDOW}s"
note "expect roughly $(( ${#TOPICS[@]} * BW_WINDOW * 2 / 60 )) min — ROSY_BW_WINDOW 로 줄일 수 있으나 0.2 Hz 토픽은 30s 미만이면 표본이 거의 없다"

#: 이 토픽들은 latched 라 첫 샘플 뒤 0 으로 읽힌다 — 0 을 트래픽 없음으로 읽지 않기 위해.
LATCHED_RE='/(map|tf_static)$'

subscriber_count() {
  # 붙기 전 구독자 수. 함정 1 때문에 이 수가 0 이면 뒤이은 측정값은
  # 내가 켠 트래픽이다.
  "${EX[@]}" ros2 topic info "$1" 2>/dev/null \
    | sed -n 's/^Subscription count: //p' | tail -n 1 || true
}

topic_type() {
  # 없는 토픽은 정상 경로다 — publish_voxel_map: False 면 voxel_grid 는 아예
  # 생성되지 않는다. `set -e` + pipefail 이 그 실패를 스크립트 종료로 바꾸면
  # 보고서가 그 줄에서 조용히 끊긴다. 실제로 한 번 그랬다.
  "${EX[@]}" ros2 topic type "$1" 2>/dev/null | head -n 1 || true
}

measure_topic() {
  local topic="$1" subs type bw hz
  subs="$(subscriber_count "$topic")"; subs="${subs:-?}"
  type="$(topic_type "$topic")"
  if [[ -z "$type" ]]; then
    printf '| `%s` | _absent_ | — | — | — | — |\n' "$topic"
    return
  fi

  bw="$("${EX[@]}" timeout -s INT "$BW_WINDOW" ros2 topic bw "$topic" 2>/dev/null \
        | tail -n 3 | grep -Eo '[0-9.]+ [KMG]?B/s' | tail -n 1 || true)"
  hz="$("${EX[@]}" timeout -s INT "$BW_WINDOW" ros2 topic hz "$topic" 2>/dev/null \
        | grep -Eo 'average rate: [0-9.]+' | tail -n 1 | sed 's/average rate: //' || true)"

  if [[ -z "$bw" ]]; then
    # 표본이 없다. RELIABLE 로 붙어 BEST_EFFORT 퍼블리셔와 안 맞았거나(함정 2),
    # latched 라 이미 다 받았거나(함정 3), 정말 발행이 없는 것이다.
    if [[ "$topic" =~ $LATCHED_RE ]]; then
      bw="_latched — 첫 샘플 이후 0, 트래픽 없음이 아님_"
    else
      bw="**UNMATCHED — 재측정 필요** (RELIABLE 구독이 안 붙었을 수 있음)"
    fi
  fi
  printf '| `%s` | `%s` | %s | %s | %s | %s |\n' \
    "$topic" "$type" "${hz:-—}" "$bw" "$subs" \
    "$([[ "$subs" == "0" ]] && echo '**측정이 트래픽을 만듦**' || echo '기존 구독자 있음')"
}

container_cpu() {
  # rosy-core 만 재면 Nav2 가 보이지 않는다 — 코스트맵을 만드는 쪽은 rosy-io 다.
  local ids
  ids="$("${DC[@]}" ps -q rosy-core rosy-io 2>/dev/null | tr '\n' ' ')"
  [[ -n "$ids" ]] || { echo "(containers not resolvable)"; return; }
  # shellcheck disable=SC2086
  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' $ids
}

# --- 보고서 ----------------------------------------------------------------

mkdir -p "$(dirname "$OUT")"
{
  echo "# DDS 베이스라인 — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo '## 환경'
  echo
  echo '| 항목 | 값 |'
  echo '|---|---|'
  echo "| ROS_DOMAIN_ID | \`$DOMAIN\` |"
  echo "| ROSY_NAMESPACE | \`$NS\` |"
  echo "| ROSY_RUNTIME_MODE | \`$MODE\` |"
  echo "| 측정 창 (bw/hz) | ${BW_WINDOW}s |"
  echo "| CPU 창 | ${CPU_WINDOW}s, idle 반복 ${IDLE_REPEATS}회 |"
  echo "| \`top\` 존재 | $HAS_TOP |"
  echo "| 이미지 | $("${DC[@]}" images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | tr '\n' ' ') |"
  echo "| host uname | $(uname -srm) |"
  echo
  echo '### 맵 크기'
  echo
  echo '```'
  "${EX[@]}" sh -c 'cat "$ROSY_MAP"' 2>/dev/null || echo '(map yaml unreadable)'
  echo '```'
  echo
  echo '## 토픽'
  echo
  echo '> 구독자 수는 `ros2 topic bw` 를 붙이기 **전**의 값이다. 0 이면 Nav2 는'
  echo '> 원래 그 토픽을 발행하지 않고 있었고, 측정이 트래픽을 만든 것이다'
  echo '> (`Costmap2DPublisher::publishCostmap()` 의 `get_subscription_count() > 0` 게이트).'
  echo
  echo '| 토픽 | 타입 | Hz | 대역폭 | 사전 구독자 | 해석 |'
  echo '|---|---|---|---|---|---|'
  i=0
  for t in "${TOPICS[@]}"; do
    i=$((i + 1))
    note "[$i/${#TOPICS[@]}] $t"
    measure_topic "$t"
  done
  echo
  echo '## CPU'
  echo
  echo '### idle'
  echo
  for i in $(seq 1 "$IDLE_REPEATS"); do
    echo "반복 $i:"
    echo '```'
    container_cpu
    echo '```'
    sleep 2
  done
  echo
  echo '> 위 세 회차의 폭이 노이즈 바닥이다. 이보다 작은 변화는 개선이 아니다.'
  echo
  echo '### navigate_to_pose 주행 중'
  echo
  echo '목표를 하나 보내고 주행이 시작된 뒤 아래를 실행하라:'
  echo
  echo '```bash'
  echo "docker compose --env-file .env --profile hardware exec -T rosy-io \\"
  echo "  ros2 action send_goal $NS/navigate_to_pose nav2_msgs/action/NavigateToPose '{...}'"
  echo "docker stats --no-stream \$(docker compose --env-file .env --profile hardware ps -q rosy-core rosy-io)"
  echo '```'
  echo
  echo '## 브라우저 유무'
  echo
  echo '이 보고서는 한 조건만 담는다. **대시보드를 연 채로 한 번, 아무도 열지'
  echo '않은 채로 한 번** 돌려서 두 파일을 비교하라. 그 차이가 수요 기반 충전'
  echo '(Option D)이 가져갈 몫이며, 어느 쪽이든 기록에 남을 값이다.'
} > "$OUT"

echo "wrote: $OUT"
