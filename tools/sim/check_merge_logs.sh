#!/bin/bash
python3 - <<'PYEOF'
import subprocess, re, sys

def entries_of(text):
    # 헤딩으로 분해: (heading, body) 목록
    lines = text.split("\n")
    out, cur_h, cur_b = [], None, []
    for ln in lines:
        if ln.startswith("## "):
            if cur_h is not None:
                out.append((cur_h, "\n".join(cur_b).strip()))
            cur_h, cur_b = ln, []
        elif cur_h is not None:
            cur_b.append(ln)
    if cur_h is not None:
        out.append((cur_h, "\n".join(cur_b).strip()))
    return out

for path in ("docs/logs.md", "control/logs.md"):
    old = subprocess.run(["git", "show", f"12c1f9650e9b:{path}"], capture_output=True).stdout.decode("utf-8")
    new = open(path, encoding="utf-8").read()
    eo, en = entries_of(old), entries_of(new)
    ho = [h for h, b in eo]; hn = [h for h, b in en]
    print(f"== {path}: old {len(eo)} entries, new {len(en)} entries")
    missing = [h for h, b in eo if (h, b) not in en]
    print("  옛 항목 중 새 버전에 없는 것(변형/유실):", len(missing))
    for h in missing[:3]:
        print("   -", h[:90])
    added = [h for h, b in en if (h, b) not in eo]
    print("  새로 추가된 항목:", len(added))
    for h in added[:4]:
        print("   +", h[:90])
PYEOF