#!/bin/bash
echo "--- ports ---"
ss -tlnp 2>/dev/null | grep -E '18080|18081' || echo "18080/18081 무청취"
echo "--- core procs ---"
ps aux | grep -E '[c]ore' | grep -v grep | head -5
echo "--- fleet state now ---"
curl -s --max-time 5 http://127.0.0.1:8090/api/fleet/state | head -c 500
echo
