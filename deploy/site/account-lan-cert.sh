#!/bin/sh
# D-1064: issue the Account LAN alias leaf from the site CA. Run as root on the site host:
#   sudo sh /opt/rosy/candidate/deploy/site/account-lan-cert.sh <alias>.local [days]
# Writes /etc/rosy/account-lan-tls/account-lan.{crt,key} (dir 0700, files 0400, UID 10001).
# The CA key never leaves ROSY_SITE_SECRETS_DIR; the existing site leaf is not touched.
set -eu
host=${1:?usage: account-lan-cert.sh <alias>.local [days]}
days=${2:-397}
ca=${ROSY_SITE_SECRETS_DIR:-/etc/rosy/site-secrets}
out=/etc/rosy/account-lan-tls
printf '%s\n' "$host" | grep -Eq '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.local$' \
  || { echo "alias must be one lowercase .local label: $host" >&2; exit 2; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
umask 077
openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
  -keyout "$work/key" -subj "/CN=$host" -out "$work/csr" 2>/dev/null
cat > "$work/ext" <<EOF
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = DNS:$host
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
EOF
openssl x509 -req -in "$work/csr" -CA "$ca/site-ca.crt" -CAkey "$ca/site-ca.key" \
  -set_serial "0x$(openssl rand -hex 16)" -days "$days" -sha256 -extfile "$work/ext" -out "$work/crt" 2>/dev/null
# Same gate as README "Site certificate profile".
openssl verify -x509_strict -purpose sslserver -verify_hostname "$host" -CAfile "$ca/site-ca.crt" "$work/crt"
install -d -o 10001 -g 10001 -m 0700 "$out"
install -o 10001 -g 10001 -m 0400 "$work/key" "$out/account-lan.key.new"
install -o 10001 -g 10001 -m 0400 "$work/crt" "$out/account-lan.crt.new"
mv -f "$out/account-lan.key.new" "$out/account-lan.key"
mv -f "$out/account-lan.crt.new" "$out/account-lan.crt"
echo "issued $out/account-lan.crt for $host; restart the proxy to load it"
