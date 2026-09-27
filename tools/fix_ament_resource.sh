#!/usr/bin/env bash
# Recreate ament resource/<pkg> markers for Python packages in the domain groups.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for d in src/contracts/* src/runtime/* src/hmi/* src/products/*/* src/drivers/* src/sim/* src/site/*; do
  if [ -f "$d/setup.py" ]; then
    pkg=$(python3 -c 'import sys, xml.etree.ElementTree as ET; name = ET.parse(sys.argv[1]).getroot().findtext("name"); assert name; print(name)' "$d/package.xml")
    mkdir -p "$d/resource"
    touch "$d/resource/$pkg"
  fi
done
