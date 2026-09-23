#!/bin/bash
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
Y=/tmp/rosy_gz_multi_9k5mc7q0/nav2_rosy_01.yaml
echo "--- nav2 yaml 의 맵 파일 참조 ---"
grep -B2 -A4 -iE 'map_server|yaml_filename' "$Y" 2>/dev/null | head -20
MAPY=$(grep -oE "yaml_filename:[: ]*'?[^']+'" "$Y" 2>/dev/null | head -1 | sed "s/yaml_filename:[: ]*'//; s/'//")
echo "map yaml: '$MAPY'"
if [ -n "$MAPY" ]; then
  if [ -f "$MAPY" ]; then echo "맵 yaml 존재함 ✓"; head -4 "$MAPY";
    PNG=$(grep -oE 'image: .*' "$MAPY" | head -1 | sed 's/image: //')
    D=$(dirname "$MAPY"); if [ -f "$D/$PNG" ]; then echo "이미지 존재 ✓: $D/$PNG"; else echo "이미지 없음 ✗: $D/$PNG"; fi
  else
    echo "맵 yaml 파일이 없다 ✗ — map_server 가 로드 실패 → /map 없음 → AMCL 불가 → map TF 없음 → PLANNING 정체"
    # 리포 트리에서 후보 탐색
    find "$REPO/src/apps/control/map" -name "*.yaml" 2>/dev/null | head -5
  fi
fi
echo "--- lifecycle/lifecycle 미사용 여부: map_server 프로세스 ---"
ps aux | grep -E '[m]ap_server' | head -3 || echo "map_server 프로세스 없음"
