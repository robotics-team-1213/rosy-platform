#!/usr/bin/env bash
# measure-resident-cpu.sh — 상주 단위별 CPU 측정·A/B (D-347 B레인 관문 측정)
#
# 절차·판정 기준: docs/plans/2026-09-29-on-demand-activation-measurement-baseline.md
# 사용:
#   sudo ./measure-resident-cpu.sh                     # 현 상태 그대로 60 s 측정
#   sudo ./measure-resident-cpu.sh --ab-unit rosy-camera.service 120
#
# A/B 는 ①단위가 켜진 상태 측정 → ②systemctl stop → 측정 → ③systemctl start 로
# 되살리고, 두 표의 차를 보고한다. A/B 허용 단위는 rosy-camera.service 와
# rosy-navigation.service 뿐이다 — rosy-core 는 게이트웨이, rosy-io 는 안전·구동
# 기본층이므로 측정 중 멈추는 것을 금지한다(기준선 문서 §2).
#
# 측정은 /proc/<pid>/stat 의 utime+stime 증분(클록 틱)을 cgroup 단위로 합산한다.
# 의존 설치 없음. 결과는 stdout 요약 + /var/lib/rosy/resident-cpu-<ts>.md.
set -euo pipefail

AB_UNIT=""
DURATION=60

allowlist_check() {
  case "$1" in
    "") ;;
    rosy-camera.service|rosy-navigation.service) ;;
    *)
      echo "A/B 불가 단위: $1" >&2
      echo "허용: rosy-camera.service, rosy-navigation.service (rosy-core·rosy-io 금지)" >&2
      return 1
      ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ab-unit) AB_UNIT="$2"; shift 2 ;;
    --ab-unit=*) AB_UNIT="${1#*=}"; shift ;;
    *) DURATION="$1"; shift ;;
  esac
done
allowlist_check "$AB_UNIT" || exit 2

if [ "$(id -u)" -ne 0 ]; then
  echo "root(sudo) 필요 — cgroup 읽기와 A/B 의 systemctl 때문이다." >&2
  exit 1
fi
case "$DURATION" in
  ''|*[!0-9]*|0) echo "duration 은 양의 초 수여야 한다: $DURATION" >&2; exit 2 ;;
esac

UNITS="rosy-core.service rosy-io.service rosy-camera.service rosy-navigation.service"
TCK="$(getconf CLK_TCK)"
NCPUS="$(nproc)"

pids_of() {  # unit -> cgroup 의 모든 pid (자식 포함)
  local unit="$1" cg
  for cg in /sys/fs/cgroup/system.slice/"$unit" \
            /sys/fs/cgroup/system.slice/"$unit".service; do
    if [ -f "$cg/cgroup.procs" ]; then
      cat "$cg/cgroup.procs"
      return 0
    fi
  done
  # cgroup 경로를 못 찾으면 MainPID 라도 (idle 유닛은 이 값이 0)
  systemctl show -p MainPID --value "$unit" 2>/dev/null || true
}

ticks() {  # unit -> utime+stime 합 (틱)
  local unit="$1" pid t total=0
  for pid in $(pids_of "$unit"); do
    [ "$pid" = "0" ] && continue
    t=$(awk '{print $14 + $15}' "/proc/$pid/stat" 2>/dev/null || echo 0)
    total=$((total + t))
  done
  echo "$total"
}

sample() {  # label -> "unit pct procs" 표를 stdout
  local label="$1" unit before after delta pct procs
  echo "## $label (duration=${DURATION}s, load=$(cut -d' ' -f1-3 /proc/loadavg), backend=${ROSY_NAVIGATION_BACKEND:-unknown})"
  echo "| unit | %CPU (1 core = 100%) | procs |"
  echo "|---|---|---|"
  for unit in $UNITS; do
    before=$(ticks "$unit")
    procs=$(pids_of "$unit" | grep -c . || true)
    sleep "$DURATION"
    after=$(ticks "$unit")
    delta=$((after - before))
    pct=$(awk -v d="$delta" -v s="$DURATION" -v t="$TCK" -v n="$NCPUS" \
      'BEGIN { printf "%.1f", d / (s * t * n) * 100 }')
    echo "| $unit | $pct | $procs |"
  done
}

OUT="/var/lib/rosy/resident-cpu-$(date +%Y%m%d-%H%M%S).md"
mkdir -p /var/lib/rosy
{
  echo "# resident-cpu $(date -Is)"
  echo "도구: deploy/robot/pinky_pro/verify/measure-resident-cpu.sh · 판정 기준은 기준선 문서 §5"
  echo
  if [ -n "$AB_UNIT" ]; then
    systemctl is-active --quiet "$AB_UNIT" || { echo "A/B 대상이 active 가 아니다: $AB_UNIT" >&2; exit 3; }
    sample "with $AB_UNIT"
    systemctl stop "$AB_UNIT"
    sleep 2
    sample "without $AB_UNIT"
    systemctl start "$AB_UNIT"   # 되살리기는 무조건 — 측정 도구가 상태를 바꾸고 끝내지 않는다
    echo
    echo "A/B 완료 후 $AB_UNIT 상태: $(systemctl is-active "$AB_UNIT")"
  else
    sample "as-is"
  fi
} | tee "$OUT"
echo
echo "기록: $OUT"
