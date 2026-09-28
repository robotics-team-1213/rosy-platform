#!/usr/bin/env bash
# Fetch and verify the exact Ubuntu Raspberry Pi base image declared in the lock.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="$SCRIPT_DIR/inputs.lock.yaml"
CACHE_DIR="${ROSY_IMAGE_CACHE:-$SCRIPT_DIR/cache}"
GPGV="${ROSY_GPGV:-gpgv}"
OFFLINE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lock) LOCK="${2:-}"; shift 2 ;;
        --cache-dir) CACHE_DIR="${2:-}"; shift 2 ;;
        --offline) OFFLINE=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -f "$LOCK" ]] || fail "missing lock file: $LOCK"

lock_value() {
    local wanted="$1"
    awk -v wanted="$wanted" '
        /^base_image:[[:space:]]*$/ { in_base=1; next }
        in_base && /^[^[:space:]]/ { exit }
        in_base {
            key=$1
            sub(/:$/, "", key)
            if (key == wanted) {
                $1=""
                sub(/^[[:space:]]+/, "")
                sub(/\r$/, "")
                gsub(/^['\''"]|['\''"]$/, "")
                print
                exit
            }
        }
    ' "$LOCK"
}

URL="$(lock_value url)"
EXPECTED_SHA256="$(lock_value sha256)"
MINIMUM_SIZE="$(lock_value minimum_size_bytes)"
CHECKSUM_URL="$(lock_value checksum_url)"
CHECKSUM_SIGNATURE_URL="$(lock_value checksum_signature_url)"
EXPECTED_SIGNING_FINGERPRINT="$(lock_value checksum_signing_key_fingerprint)"
CHECKSUM_KEYRING="$(lock_value checksum_keyring)"

[[ "$URL" == https://* ]] || fail "base image must use a pinned HTTPS URL"
[[ "${URL,,}" != *latest* ]] || fail "base image must use a pinned HTTPS URL, not latest"
[[ "$CHECKSUM_URL" == https://* && "$CHECKSUM_SIGNATURE_URL" == https://* ]] \
    || fail "Canonical checksum metadata must use pinned HTTPS URLs"
[[ "${CHECKSUM_URL,,}" != *latest* && "${CHECKSUM_SIGNATURE_URL,,}" != *latest* ]] \
    || fail "Canonical checksum metadata must not use latest URLs"
[[ "$EXPECTED_SHA256" =~ ^[0-9a-fA-F]{64}$ ]] \
    || fail "base image sha256 must be a pinned 64-character digest"
[[ "$MINIMUM_SIZE" =~ ^[1-9][0-9]*$ ]] \
    || fail "base image minimum_size_bytes must be a positive integer"
[[ "$EXPECTED_SIGNING_FINGERPRINT" =~ ^[0-9A-F]{40}$ ]] \
    || fail "Canonical signing-key fingerprint must be 40 uppercase hexadecimal characters"

URL_PATH="${URL%%\?*}"
FILENAME="${URL_PATH##*/}"
[[ -n "$FILENAME" && "$FILENAME" != "$URL_PATH" ]] \
    || fail "base image URL has no filename"

RELEASE_URL="${URL_PATH%/*}"
[[ "$CHECKSUM_URL" == "$RELEASE_URL/SHA256SUMS" ]] \
    || fail "checksum URL must use the exact pinned base-image release directory"
[[ "$CHECKSUM_SIGNATURE_URL" == "$RELEASE_URL/SHA256SUMS.gpg" ]] \
    || fail "checksum signature URL must use the exact pinned base-image release directory"

LOCK_DIR="$(cd "$(dirname "$LOCK")" && pwd)"
if [[ "$CHECKSUM_KEYRING" != /* ]]; then
    CHECKSUM_KEYRING="$LOCK_DIR/$CHECKSUM_KEYRING"
fi
[[ -f "$CHECKSUM_KEYRING" ]] || fail "missing Canonical image-signing keyring: $CHECKSUM_KEYRING"
command -v "$GPGV" >/dev/null 2>&1 || fail "gpgv is required to verify Canonical checksum metadata"

mkdir -p "$CACHE_DIR"
DEST="$CACHE_DIR/$FILENAME"
SUMS_PATH="$CACHE_DIR/SHA256SUMS"
SIGNATURE_PATH="$CACHE_DIR/SHA256SUMS.gpg"
TEMP_FILES=()
cleanup() {
    if (( ${#TEMP_FILES[@]} > 0 )); then
        rm -f -- "${TEMP_FILES[@]}"
    fi
}
trap cleanup EXIT

fetch_metadata() {
    local url="$1" destination="$2" label="$3"
    if [[ -f "$destination" ]]; then
        FETCHED_PATH="$destination"
        return
    fi

    (( OFFLINE == 0 )) || fail "Canonical $label is missing in offline mode: $destination"
    command -v curl >/dev/null 2>&1 || fail "curl is required to fetch Canonical checksum metadata"

    local part="$destination.part.$$"
    TEMP_FILES+=("$part")
    curl --fail --location --proto '=https' --proto-redir '=https' \
        --retry 3 --output "$part" "$url"
    FETCHED_PATH="$part"
}

fetch_metadata "$CHECKSUM_URL" "$SUMS_PATH" "checksum list"
SUMS_CANDIDATE="$FETCHED_PATH"
fetch_metadata "$CHECKSUM_SIGNATURE_URL" "$SIGNATURE_PATH" "checksum signature"
SIGNATURE_CANDIDATE="$FETCHED_PATH"

if ! GPG_STATUS="$("$GPGV" --status-fd 1 --keyring "$CHECKSUM_KEYRING" \
        "$SIGNATURE_CANDIDATE" "$SUMS_CANDIDATE" 2>&1)"; then
    fail "Canonical checksum signature verification failed"
fi

VALID_FINGERPRINTS="$(printf '%s\n' "$GPG_STATUS" | awk '
    $1 == "[GNUPG:]" && $2 == "VALIDSIG" {
        print toupper($3)
        if (NF >= 12) print toupper($NF)
    }
')"
if ! printf '%s\n' "$VALID_FINGERPRINTS" | grep -Fxq "$EXPECTED_SIGNING_FINGERPRINT"; then
    fail "Canonical checksum signature fingerprint does not match the pinned key"
fi

if ! SIGNED_SHA256="$(awk -v wanted="$FILENAME" '
    NF >= 2 {
        name=$2
        sub(/^\*/, "", name)
        sub(/^\.\//, "", name)
        sub(/\r$/, "", name)
        if (name == wanted) {
            print tolower($1)
            matches++
        }
    }
    END { if (matches != 1) exit 1 }
' "$SUMS_CANDIDATE")"; then
    fail "signed checksum list must contain exactly one entry for $FILENAME"
fi
[[ "$SIGNED_SHA256" =~ ^[0-9a-f]{64}$ ]] \
    || fail "signed checksum for $FILENAME is not a SHA-256 digest"
[[ "$SIGNED_SHA256" == "${EXPECTED_SHA256,,}" ]] \
    || fail "signed checksum for $FILENAME does not match the lock"

if [[ "$SUMS_CANDIDATE" != "$SUMS_PATH" ]]; then
    mv -f -- "$SUMS_CANDIDATE" "$SUMS_PATH"
fi
if [[ "$SIGNATURE_CANDIDATE" != "$SIGNATURE_PATH" ]]; then
    mv -f -- "$SIGNATURE_CANDIDATE" "$SIGNATURE_PATH"
fi
echo "PROVENANCE_VERIFIED $EXPECTED_SIGNING_FINGERPRINT $FILENAME"

verify_file() {
    local candidate="$1"
    local size actual
    size="$(wc -c < "$candidate" | tr -d '[:space:]')"
    (( size >= MINIMUM_SIZE )) \
        || fail "base image is too small: $size bytes (minimum $MINIMUM_SIZE)"
    actual="$(sha256sum "$candidate" | awk '{print $1}')"
    [[ "${actual,,}" == "${EXPECTED_SHA256,,}" ]] \
        || fail "base image checksum mismatch: expected $EXPECTED_SHA256, got $actual"
}

if [[ -f "$DEST" ]]; then
    verify_file "$DEST"
    echo "CACHE_VERIFIED $DEST"
    exit 0
fi

(( OFFLINE == 0 )) || fail "verified cache is missing in offline mode: $DEST"
command -v curl >/dev/null 2>&1 || fail "curl is required to fetch the base image"

PART="$DEST.part.$$"
TEMP_FILES+=("$PART")
curl --fail --location --proto '=https' --proto-redir '=https' \
    --retry 3 --output "$PART" "$URL"
verify_file "$PART"
mv -f -- "$PART" "$DEST"
echo "DOWNLOADED_VERIFIED $DEST"
