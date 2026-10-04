#!/usr/bin/env bash
# D-346: git does not version hooks, so each clone installs them explicitly.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
# Git resolves linked worktrees and core.hooksPath (including relative paths).
hooks="$(git rev-parse --git-path hooks)"
mkdir -p "$hooks"
cp "$root/tools/hooks/pre-push" "$hooks/pre-push"
chmod +x "$hooks/pre-push"
echo "installed $hooks/pre-push (fast gate, D-346)"
