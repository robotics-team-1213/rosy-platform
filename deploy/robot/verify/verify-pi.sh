#!/usr/bin/env bash
set -Eeuo pipefail

require_internet=0
network_interface="auto"
failures=0

usage() {
  cat <<'EOF'
Usage: verify-pi.sh [--require-internet] [--interface auto|IFACE]

Checks the selected Raspberry Pi LAN interface (auto, wired, or Wi-Fi), Internet
reachability, the Rosy runtime, API, and dashboard. Internet failure is a
warning unless --require-internet is supplied.
EOF
}

while (($# > 0)); do
  case "$1" in
    --require-internet)
      require_internet=1
      ;;
    --interface)
      (($# >= 2)) || {
        echo "--interface requires auto or an interface name" >&2
        exit 2
      }
      network_interface="$2"
      shift
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

if [[ "$network_interface" != "auto" &&
      ! "$network_interface" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
  echo "Unsafe network interface name: $network_interface" >&2
  exit 2
fi

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

has_command() {
  command -v "$1" >/dev/null 2>&1
}

network_ipv4=""
default_interface=""

if ! has_command ip; then
  fail "LAN" "iproute2 is unavailable"
else
  default_interface="$(ip -4 route show default 2>/dev/null | awk '
    $1 == "default" {for (i = 1; i <= NF; i++) if ($i == "dev") {print $(i + 1); exit}}
  ' || true)"
  if [[ "$network_interface" == "auto" ]]; then
    network_interface="$default_interface"
    if [[ -z "$network_interface" ]]; then
      network_interface="$(ip -4 -o addr show scope global 2>/dev/null | awk '
        $2 != "lo" {print $2; exit}
      ' || true)"
    fi
  fi
  if [[ -z "$network_interface" || "$network_interface" == "lo" ]]; then
    fail "LAN" "no usable non-loopback network interface was selected"
  else
    network_ipv4="$(ip -4 -o addr show dev "$network_interface" scope global 2>/dev/null | awk '
      NR == 1 {split($4, address, "/"); print address[1]}
    ' || true)"
    if [[ -z "$network_ipv4" ]]; then
      fail "LAN" "$network_interface has no global IPv4 address"
    else
      pass "LAN" "$network_interface IPv4: $network_ipv4"
    fi
    if ip route show default dev "$network_interface" 2>/dev/null | grep -q '^default '; then
      pass "ROUTE" "default route through $network_interface present"
    elif ((require_internet)); then
      fail "ROUTE" "no default route (--require-internet enabled)"
    else
      warn "ROUTE" "no default route; same-LAN dashboard may still work"
    fi
  fi
fi

if [[ "$network_interface" == wlan* ]]; then
  wifi_connection=""
  if ! has_command nmcli; then
    fail "WIFI" "nmcli is unavailable; NetworkManager is required for Wi-Fi"
  elif [[ "$(nmcli radio wifi 2>/dev/null || true)" != "enabled" ]]; then
    fail "WIFI" "Wi-Fi radio is disabled"
  else
    wifi_connection="$(nmcli -t -f GENERAL.CONNECTION device show "$network_interface" 2>/dev/null | cut -d: -f2- || true)"
    if [[ -z "$wifi_connection" || "$wifi_connection" == "--" ]]; then
      fail "WIFI" "$network_interface is not associated with a Wi-Fi connection"
    else
      pass "WIFI" "$network_interface connection: $wifi_connection"
    fi
  fi
else
  pass "WIFI" "not required for selected interface: ${network_interface:-none}"
fi

dns_ok=0
if has_command getent && getent ahosts www.raspberrypi.com >/dev/null 2>&1; then
  dns_ok=1
  pass "DNS" "public hostname resolution succeeded"
else
  warn "DNS" "public hostname resolution failed"
fi

internet_ok=0
if [[ -n "$network_interface" ]] && has_command curl && \
  curl --interface "$network_interface" -fsSIL --max-time 8 https://www.raspberrypi.com/ >/dev/null 2>&1; then
  internet_ok=1
  pass "INTERNET" "outbound HTTPS succeeded"
elif ((require_internet)); then
  fail "INTERNET" "outbound HTTPS failed (--require-internet enabled)"
else
  warn "INTERNET" "outbound HTTPS failed; local dashboard may still work"
fi

# The LiDAR (ttyAMA0) and motor (ttyAMA4) buses must carry no kernel console or
# getty. Ubuntu's console=serial0 lands on ttyAMA0 with enable_uart=1 and
# sllidar_node then times out (rosy-pinky-e4us, 2026-09-24).
bus_consoles="$(tr ' ' '\n' </proc/cmdline 2>/dev/null | grep -E '^console=(serial0|ttyAMA0|ttyAMA4)(,|$)' | tr '\n' ' ' || true)"
if [[ -n "$bus_consoles" ]]; then
  fail "UART" "kernel console on a robot bus UART (${bus_consoles% }); run sudo $(dirname "$0")/../configure-uart-pi5.sh and reboot"
elif has_command systemctl && systemctl is-active --quiet serial-getty@ttyAMA0.service 2>/dev/null; then
  fail "UART" "serial-getty@ttyAMA0.service holds the LiDAR UART; run sudo $(dirname "$0")/../configure-uart-pi5.sh and reboot"
else
  pass "UART" "no console or getty on ttyAMA0 (LiDAR) / ttyAMA4 (motor)"
fi

install_root="${ROSY_INSTALL_ROOT:-/opt/rosy}"
compose_file="$install_root/deploy/robot/compose.yaml"
env_file="$install_root/deploy/robot/.env"

runtime_ok=1
configured_mode="$(sed -n 's/^ROSY_RUNTIME_MODE=//p' "$env_file" 2>/dev/null | tail -n 1)"
configured_mode="${configured_mode%$'\r'}"
configured_mode="${configured_mode:-core}"
# shellcheck source=config/resolve-mode.sh
source "$install_root/deploy/robot/config/resolve-mode.sh"
configured_mode="$(resolve_runtime_mode "$configured_mode" "$install_root/deploy/robot/config/board.yaml")" || {
  fail "RUNTIME" "unknown ROSY_RUNTIME_MODE in .env"
  runtime_ok=0
  configured_mode="core"
}
runtime_profile=()
runtime_service=""
case "$configured_mode" in
  core)
    ;;
  motor)
    runtime_profile=(--profile motor)
    runtime_service="rosy-motor"
    ;;
  hardware)
    runtime_profile=(--profile hardware)
    runtime_service="rosy-io"
    ;;
  *)
    fail "RUNTIME" "unknown ROSY_RUNTIME_MODE in .env: $configured_mode"
    runtime_ok=0
    ;;
esac
overlay="$install_root/deploy/robot/config/capabilities.${configured_mode}.yaml"
profile="$install_root/deploy/robot/config/profile.${configured_mode}.yaml"
if [[ ! -f "$overlay" || ! -f "$profile" ]]; then
  fail "RUNTIME" "missing board overlay for $configured_mode"
  runtime_ok=0
fi
if ! systemctl is-active --quiet rosy-runtime.service 2>/dev/null; then
  fail "RUNTIME" "rosy-runtime.service is not active"
  runtime_ok=0
elif ! docker compose --env-file "$env_file" -f "$compose_file" ps --status running rosy-core 2>/dev/null | grep -q 'rosy-core'; then
  fail "RUNTIME" "rosy-core container is not running"
  runtime_ok=0
fi
if [[ -n "$runtime_service" ]] && ! docker compose --env-file "$env_file" \
  -f "$compose_file" "${runtime_profile[@]}" ps --status running --services "$runtime_service" \
  2>/dev/null | grep -Fxq "$runtime_service"; then
  fail "RUNTIME" "$configured_mode mode requires running $runtime_service"
  runtime_ok=0
fi
if ((runtime_ok)); then
  pass "RUNTIME" "systemd and $configured_mode runtime containers are active"
fi

if has_command curl && curl -fsS --max-time 5 http://127.0.0.1:8080/api/v1 >/dev/null 2>&1; then
  pass "API" "FastAPI root responds locally"
else
  fail "API" "http://127.0.0.1:8080/api/v1 did not respond"
fi

if has_command curl && curl -fsS --max-time 5 http://127.0.0.1:8080/dashboard >/dev/null 2>&1; then
  pass "DASHBOARD" "dashboard responds locally"
else
  fail "DASHBOARD" "http://127.0.0.1:8080/dashboard did not respond"
fi

hostname_short="$(hostname -s 2>/dev/null || hostname)"
echo
echo "Dashboard access (client must be on the same LAN and peer traffic must be allowed):"
echo "  http://${hostname_short}.local:8080/dashboard"
if [[ -n "$network_ipv4" ]]; then
  echo "  http://${network_ipv4}:8080/dashboard"
fi

if ((dns_ok == 0 && require_internet)); then
  fail "DNS" "DNS is required for Internet-ready acceptance"
fi

if ((internet_ok == 0)); then
  echo "Internet status does not change same-LAN dashboard availability."
fi

if ((failures > 0)); then
  echo
  echo "Rosy Pi verification failed: $failures required check(s) failed." >&2
  exit 1
fi

echo
echo "Rosy Pi verification passed."
echo "Readback evidence: sudo $install_root/deploy/robot/verify/device-readback.sh --json"
