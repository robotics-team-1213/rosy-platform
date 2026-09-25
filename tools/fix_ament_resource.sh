#!/usr/bin/env bash
# Recreate ament resource/<pkg> markers for Python packages in the domain groups.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for d in src/contracts/* src/runtime/* src/devices/*/* src/hmi/* src/products/* src/sim/* src/site/*; do
  if [ -f "$d/setup.py" ]; then
    pkg=$(basename "$d")
    mkdir -p "$d/resource"
    touch "$d/resource/$pkg"
  fi
done
