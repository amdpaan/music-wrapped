#!/bin/sh
# Signs the logger with a local self-signed certificate (created once in your login keychain).
# Ad-hoc signatures change with every build, so macOS forgets the "control Music" approval each
# time; with a stable certificate it's kept across rebuilds. The certificate never leaves this Mac.
# Usage: tools/sign-logger.sh <path to music-wrapped-logger>
set -eu
BIN="$1"
NAME="music-wrapped logger (local)"
KC="$HOME/Library/Keychains/login.keychain-db"

if ! security find-certificate -c "$NAME" "$KC" >/dev/null 2>&1; then
  echo "  Creating the local signing certificate \"$NAME\" in your login keychain"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  cat > "$TMP/cert.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$TMP/cert.cnf" \
    -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null
  PASS="$(openssl rand -hex 16)"
  openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" -name "$NAME" \
    -passout "pass:$PASS" -out "$TMP/id.p12" 2>/dev/null
  security import "$TMP/id.p12" -k "$KC" -P "$PASS" -T /usr/bin/codesign >/dev/null
fi

codesign --force --sign "$NAME" --identifier com.musicwrapped.logger "$BIN"
