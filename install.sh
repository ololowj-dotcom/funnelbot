#!/usr/bin/env bash
set -euo pipefail

REPO="${FUNNELBOT_REPO:-https://github.com/ololowj-dotcom/funnelbot}"
REF="${FUNNELBOT_REF:-main}"
PREFIX="${FUNNELBOT_PREFIX:-/opt/funnelbot}"
BIN_LINK="/usr/local/bin/funnelbot"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "please run as root:  curl -fsSL <url> | sudo bash"
[ "$(uname -s)" = "Linux" ] || fail "this installer is for Linux servers; this is $(uname -s)"

pick_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null \
            && "$candidate" -c 'import venv, ensurepip' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

install_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        say "Installing Python and git with apt"
        DEBIAN_FRONTEND=noninteractive apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        say "Installing Python and git with dnf"
        dnf install -y -q python3 python3-pip git ca-certificates
    elif command -v yum >/dev/null 2>&1; then
        say "Installing Python and git with yum"
        yum install -y -q python3 python3-pip git ca-certificates
    else
        fail "could not install Python automatically. Install Python 3.10+, venv and git, then run this again"
    fi
}

PYTHON="$(pick_python || true)"
if [ -z "$PYTHON" ] || ! command -v git >/dev/null 2>&1; then
    install_packages
    PYTHON="$(pick_python || true)"
fi
[ -n "$PYTHON" ] || fail "Python 3.10 or newer with venv is required (Debian/Ubuntu: apt install python3 python3-venv)"
command -v git >/dev/null 2>&1 || fail "git is required (Debian/Ubuntu: apt install git)"

say "Creating a virtual environment in $PREFIX"
mkdir -p "$PREFIX"
"$PYTHON" -m venv "$PREFIX/venv" || fail "could not create a virtual environment (Debian/Ubuntu: apt install python3-venv)"

say "Installing funnelbot ($REF)"
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade pip
"$PREFIX/venv/bin/python" -m pip install --quiet --upgrade --force-reinstall "git+${REPO}@${REF}"

ln -sf "$PREFIX/venv/bin/funnelbot" "$BIN_LINK"
say "Installed: $("$BIN_LINK" --version)"

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet funnelbot 2>/dev/null; then
    say "Restarting the running bot with the new version"
    systemctl restart funnelbot
fi

if [ "${FUNNELBOT_NO_SETUP:-0}" = "1" ]; then
    say "Done. Next step:  sudo funnelbot setup"
    exit 0
fi

if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    say "Starting the guided setup (Ctrl+C to skip; run 'sudo funnelbot setup' later)"
    exec "$BIN_LINK" setup </dev/tty
fi
say "Done. Next step:  sudo funnelbot setup"
