#!/bin/sh
# A code-signing identity that stays the same on this Mac, so macOS keeps the Screen Recording /
# Accessibility permissions after an update. An ad-hoc signature (codesign -s -) is identified by the
# hash of the build itself, so every new build is a "new app" and the permissions must be granted again;
# a certificate is identified by "identifier com.capturetool.app and certificate leaf = <its hash>".
# Free: a self-signed certificate, no Apple developer account. It only lives on this Mac, in its own
# keychain (not the login keychain), whose random password sits in a private file - not in the repo.
#
#   sh tools/mac_signing.sh setup      create it once (running it again changes nothing)
#   sh tools/mac_signing.sh identity   print the identity for build.sh (exit 1 when there is none)
set -e
NAME="CaptureTool Local Signing"
KC="$HOME/Library/Keychains/capturetool-signing.keychain-db"
DIR="$HOME/Library/Application Support/CaptureTool-signing"
PASS_FILE="$DIR/keychain.pass"

in_search_list() { security list-keychains -d user | tr -d '" ' | grep -qx "$KC"; }

add_to_search_list() {
    # codesign only finds identities in keychains on the user's search list
    # shellcheck disable=SC2046
    in_search_list || security list-keychains -d user -s $(security list-keychains -d user | tr -d '"') "$KC"
}

identity() {
    [ -f "$KC" ] && [ -f "$PASS_FILE" ] || return 1
    security unlock-keychain -p "$(cat "$PASS_FILE")" "$KC"
    add_to_search_list
    h=$(security find-identity -p codesigning "$KC" | awk -v n="\"$NAME\"" 'index($0, n) {print $2; exit}')
    [ -n "$h" ] || return 1
    echo "$h"
}

setup() {
    if h=$(identity 2>/dev/null); then
        echo "already set up: $NAME ($h)"
        return 0
    fi
    if [ -f "$KC" ]; then
        echo "$KC exists but cannot be opened (password file missing?). Move it away and run setup again." >&2
        exit 1
    fi
    umask 077
    mkdir -p "$DIR"
    /usr/bin/openssl rand -hex 24 > "$PASS_FILE"
    pass=$(cat "$PASS_FILE")
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    cat > "$tmp/cert.cnf" <<EOF
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
EOF
    # macOS's own LibreSSL on purpose: a .p12 from OpenSSL 3/4 (Homebrew) uses a format `security import`
    # cannot read ("MAC verification failed")
    /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$tmp/cert.cnf" \
        -keyout "$tmp/key.pem" -out "$tmp/cert.pem" 2>/dev/null
    /usr/bin/openssl pkcs12 -export -inkey "$tmp/key.pem" -in "$tmp/cert.pem" -name "$NAME" \
        -out "$tmp/id.p12" -passout "pass:$pass"
    security create-keychain -p "$pass" "$KC"
    security set-keychain-settings "$KC"                  # no auto-lock
    security unlock-keychain -p "$pass" "$KC"
    security import "$tmp/id.p12" -k "$KC" -P "$pass" -T /usr/bin/codesign >/dev/null
    security set-key-partition-list -S apple-tool:,apple: -s -k "$pass" "$KC" >/dev/null   # codesign without a prompt
    add_to_search_list
    h=$(identity)
    echo "created: $NAME ($h) - valid for 10 years"
}

case "$1" in
    setup) setup ;;
    identity) identity ;;
    *) echo "usage: sh tools/mac_signing.sh setup|identity" >&2; exit 2 ;;
esac
