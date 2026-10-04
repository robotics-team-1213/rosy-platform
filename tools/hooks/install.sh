#!/usr/bin/env bash
# D-346: git does not version hooks, so each clone installs them explicitly.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
# Git resolves linked worktrees and core.hooksPath (including relative paths).
hooks="$(git rev-parse --git-path hooks)"
mkdir -p "$hooks"
# Preserve the existing same-file refusal for tracked core.hooksPath layouts.
if [ "$root/tools/hooks/pre-push" -ef "$hooks/pre-push" ]; then
  echo 'configured hook is already the source; no installation performed' >&2
  exit 2
fi
# Git for Windows may check out extensionless hooks with CRLF.
sed 's/\r$//' "$root/tools/hooks/pre-push" > "$hooks/pre-push"
chmod +x "$hooks/pre-push"
echo "installed $hooks/pre-push (fast gate, D-346)"
