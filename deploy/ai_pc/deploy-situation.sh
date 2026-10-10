#!/bin/sh
# D-577: run rosy-situation from one known commit on the AI PC (`ai` account; owner consent D-492, 2026-10-10).
# Each commit gets its own detached worktree under ~/rosy-situation/<sha>; `current` points at the live one,
# so the heartbeat's build_commit (console 연동 상태 row, GET /api/fleet/ai) names exactly what runs.
# Usage: deploy-situation.sh <commit-ish>      Rollback: deploy-situation.sh <previous sha>
set -eu
commit=${1:?usage: deploy-situation.sh <commit-ish>}
repo=${ROSY_REPO:-$HOME/rosy-platform}
root=$HOME/rosy-situation
git -C "$repo" fetch --quiet origin
sha=$(git -C "$repo" rev-parse --verify "$commit^{commit}")
short=$(git -C "$repo" rev-parse --short=12 "$sha")
mkdir -p "$root"
[ -d "$root/$short" ] || git -C "$repo" worktree add --detach "$root/$short" "$sha"
ln -sfn "$root/$short" "$root/current"
cp "$root/$short/deploy/ai_pc/rosy-situation.service" "$HOME/.config/systemd/user/rosy-situation.service"
systemctl --user daemon-reload
systemctl --user restart rosy-situation.service
echo "rosy-situation runs $short; check build_commit on the console 연동 상태 row"
