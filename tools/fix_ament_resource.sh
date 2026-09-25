#!/usr/bin/env bash
# Recreate ament resource/<pkg> markers for Python packages in the domain groups.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for d in src/apps/* src/contracts/* src/core/* src/devices/* src/face/* src/products/* src/navigation/* src/sim/* src/site/*; do
  if [ -f "$d/setup.py" ]; then
    pkg=$(basename "$d")
    mkdir -p "$d/resource"
    touch "$d/resource/$pkg"
  fi
done
