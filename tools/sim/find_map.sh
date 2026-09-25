#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
D="$REPO/src/runtime/control/map/map_260905_update_v2"
find "$D" \( -name '*.yaml' -o -name '*.pgm' \) 2>/dev/null | head -8
echo "--- yaml 내용 ---"
for f in $(find "$D" -name '*.yaml' 2>/dev/null | head -2); do
  echo "[$f]"
  head -4 "$f"
done
