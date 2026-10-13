#!/usr/bin/env bash
# Recreate ament resource/<pkg> markers for the current product source roots.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while IFS= read -r setup; do
  d=$(dirname "$setup")
  if [ -f "$d/package.xml" ]; then
    pkg=$(python3 -c 'import sys, xml.etree.ElementTree as ET; name = ET.parse(sys.argv[1]).getroot().findtext("name"); assert name; print(name)' "$d/package.xml")
    mkdir -p "$d/resource"
    touch "$d/resource/$pkg"
  fi
done < <(find contracts middleware operations integrations learning -name setup.py -not -path '*/test/*' -not -path '*/tests/*')
