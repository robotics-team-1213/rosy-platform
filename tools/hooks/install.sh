#!/usr/bin/env bash
# D-346: git does not version hooks, so each clone installs them explicitly.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
mkdir -p "$root/.git/hooks"
cp "$root/tools/hooks/pre-push" "$root/.git/hooks/pre-push"
chmod +x "$root/.git/hooks/pre-push"
echo "installed .git/hooks/pre-push (fast gate, D-346)"
