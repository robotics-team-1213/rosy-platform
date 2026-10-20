#!/usr/bin/env bash
# 런치 프로세스(555)가 무엇을 하고 막혔는지 확인
pid=555
echo "=== status ==="
grep -E "State|Threads" /proc/$pid/status 2>/dev/null
echo "=== wchan ==="
cat /proc/$pid/wchan 2>/dev/null; echo
echo "=== open files (tail) ==="
ls -l /proc/$pid/fd 2>/dev/null | tail -6
echo "=== cpu time ==="
cat /proc/$pid/stat 2>/dev/null | awk '{print "utime:"$14" stime:"$15}'
