#!/bin/sh
# D-179 bench apply. Filesystem changes and the compose/drop-in decision stay in Python.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
echo "재부팅과 rosy-runtime 재시작은 이미지 코드로 돌아가고 마커 HOLD가 남으니, 같은 동기화를 다시 실행한다."
exec python3 -B "$SCRIPT_DIR/core_dev_overlay.py" "$@"
