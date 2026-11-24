#!/usr/bin/env bash
# Fetch a CI-built, operator-signed site candidate from GitHub Releases (D-437).
#
#   deploy/site/fetch_candidate.sh --repo <owner>/<repository> --commit <40-hex sha> \
#       [--staging DIR]
#
# Runs on the site host as the operator, without sudo. Downloads the public
# prerelease site-<sha12> assets, checks SHA256SUMS, reassembles the split tar,
# extracts it into a fresh staging folder, and adds release.json.sig. It does
# NOT authenticate the candidate: SHA256SUMS is unsigned. The independently
# installed verify_candidate.py does that (D-301); the commands to run next are
# printed at the end. Refuses a release without release.json.sig (unsigned).
# Needs curl, sha256sum and python3 >= 3.12 (safe tar extraction).
set -euo pipefail

REPO=
COMMIT=
STAGING="${HOME}/rosy-site-staging"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=$2; shift ;;
    --commit) COMMIT=$2; shift ;;
    --staging) STAGING=$2; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

[[ "$REPO" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || { echo "--repo must be owner/repository" >&2; exit 2; }
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] \
  || { echo "--commit must be the full 40-character source commit" >&2; exit 2; }

TAG="site-${COMMIT:0:12}"
BASE="https://github.com/${REPO}/releases/download/${TAG}"
WORK="${STAGING}/${TAG}"
DOWNLOAD="${WORK}/download"
CANDIDATE="${WORK}/candidate"
PARTS="rosy-site-candidate-${COMMIT}.tar.part"

if [ -e "$WORK" ]; then
  echo "staging folder already exists, remove it first: $WORK" >&2
  exit 1
fi
mkdir -p "$DOWNLOAD" "$CANDIDATE"

fetch() {
  curl --fail --silent --show-error --location --retry 3 \
    --proto '=https' --proto-redir '=https' \
    --output "${DOWNLOAD}/$1" "${BASE}/$1"
}

fetch SHA256SUMS
if ! fetch release.json.sig; then
  echo "release ${TAG} has no release.json.sig: it is UNSIGNED, sign it first" >&2
  exit 1
fi

# Only the expected asset names may appear; anything else is refused.
while read -r digest name; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || { echo "bad SHA256SUMS line" >&2; exit 1; }
  case "$name" in
    release.json) ;;
    "${PARTS}"[0-9][0-9]) ;;
    *) echo "unexpected asset in SHA256SUMS: $name" >&2; exit 1 ;;
  esac
  fetch "$name"
done <"${DOWNLOAD}/SHA256SUMS"
(cd "$DOWNLOAD" && sha256sum --check --strict SHA256SUMS)

ARCHIVE="${DOWNLOAD}/rosy-site-candidate-${COMMIT}.tar"
cat "${DOWNLOAD}/${PARTS}"[0-9][0-9] >"$ARCHIVE"
rm -f "${DOWNLOAD}/${PARTS}"[0-9][0-9]

# Check every member before extracting anything: only regular files and
# directories under <commit>/ (no symlink, hardlink, device, fifo, absolute
# path or ..), then extract with tarfile's "data" filter as a second guard.
python3 - "$ARCHIVE" "$CANDIDATE" "$COMMIT" <<'PY'
import sys
import tarfile

if sys.version_info < (3, 12):
    sys.exit("python3 >= 3.12 is required (tarfile data extraction filter)")
archive, destination, commit = sys.argv[1:]
with tarfile.open(archive, "r:") as bundle:
    members = bundle.getmembers()
    for member in members:
        name = member.name
        if not (member.isfile() or member.isdir()):
            sys.exit(f"refusing non-regular archive member: {name}")
        if (name.startswith("/") or ".." in name.split("/")
                or not (name == commit or name.startswith(commit + "/"))):
            sys.exit(f"unexpected archive member: {name}")
    bundle.extractall(destination, members=members, filter="data")
PY
rm -f "$ARCHIVE"

DIR="${CANDIDATE}/${COMMIT}"
cmp "${DOWNLOAD}/release.json" "${DIR}/release.json"
cp "${DOWNLOAD}/release.json.sig" "${DIR}/release.json.sig"

cat <<EOF
Staged ${TAG} (UNVERIFIED) at:
  ${DIR}

Next, as the administrator (verifier and public key installed out-of-band, D-301):
  SITE_KEY_ID=<site-signing-key-id>
  SITE_PUBLIC_KEY=/etc/rosy/site/trust/site-release-ed25519.pub.pem
  sudo bash -euo pipefail -c '
    DST="/opt/rosy/candidates/\$2"
    CREATED_FREEZE=0
    STOPPED_MAINT=0
    tmp=""
    cleanup() {
      rm -rf "\$DST.new" /opt/rosy/.candidate.tmp "\${tmp:-}"
      if [ "\$CREATED_FREEZE" = 1 ]; then rm -f /etc/rosy/update-freeze; fi
      if [ "\$STOPPED_MAINT" = 1 ]; then systemctl start rosy-root-maintenance.timer || true; fi
    }
    trap cleanup EXIT
    python3 /usr/local/lib/rosy-site/verify_candidate.py --candidate-dir "\$1" \\
      --trusted-key-id "\$3" --trusted-public-key "\$4" --signature-only
    if systemctl is-active --quiet rosy-root-maintenance.timer 2>/dev/null; then
      systemctl stop rosy-root-maintenance.timer
      STOPPED_MAINT=1
    fi
    if [ ! -e /etc/rosy/update-freeze ]; then
      touch /etc/rosy/update-freeze
      CREATED_FREEZE=1
    fi
    for unit in rosy-root-maintenance.service rosy-site-autoupdate.service; do
      for _i in \$(seq 1 150); do
        st=\$(systemctl show -p ActiveState --value "\$unit" 2>/dev/null || echo unknown)
        if [ "\$st" = "inactive" ] || [ "\$st" = "failed" ]; then break; fi
        sleep 2
      done
      st=\$(systemctl show -p ActiveState --value "\$unit")
      [ "\$st" = "inactive" ] || [ "\$st" = "failed" ]
    done
    [ ! -L /run/lock/rosy-site-autoupdate.lock ]
    exec 9>/run/lock/rosy-site-autoupdate.lock
    flock -w 300 9
    cur=\$(readlink -f /opt/rosy/candidate 2>/dev/null || true)
    if { [ -L /opt/rosy/candidate ] || [ -e /opt/rosy/candidate ]; } && [ "\$cur" = "\$DST" ]; then
      echo "refused: \$DST is already the active candidate" >&2
      exit 1
    fi
    mkdir -p /opt/rosy/candidates
    rm -rf "\$DST.new" "\$DST" && cp -a "\$1" "\$DST.new"
    chown -R root:root "\$DST.new" && chmod -R u+rwX,go+rX "\$DST.new"
    mv -T "\$DST.new" "\$DST"
    docker image load --input "\$DST/images.tar"
    python3 /usr/local/lib/rosy-site/verify_candidate.py --candidate-dir "\$DST" \\
      --trusted-key-id "\$3" --trusted-public-key "\$4"
    grep -q "^ROSY_SITE_IMAGE_TAG=" /etc/rosy/site/site.env
    cp -p /etc/rosy/site/site.env /etc/rosy/site/site.env.manual-prev
    tmp=\$(mktemp /etc/rosy/site/.site.env.XXXXXX)
    sed "s|^ROSY_SITE_IMAGE_TAG=.*|ROSY_SITE_IMAGE_TAG=\$2|" /etc/rosy/site/site.env > "\$tmp"
    chmod --reference=/etc/rosy/site/site.env "\$tmp" && mv -Tf "\$tmp" /etc/rosy/site/site.env
    tmp=""
    if [ -d /opt/rosy/candidate ] && [ ! -L /opt/rosy/candidate ]; then
      mv /opt/rosy/candidate "/opt/rosy/candidate.prev.\$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    ln -sfn "\$DST" /opt/rosy/.candidate.tmp && mv -Tf /opt/rosy/.candidate.tmp /opt/rosy/candidate
    systemctl restart rosy-site-stack.service
  ' _ "${DIR}" "${COMMIT}" "\$SITE_KEY_ID" "\$SITE_PUBLIC_KEY"
EOF
