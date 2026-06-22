#!/bin/bash
# Bob Frm Mktg — compatibility setup launcher

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VERSION="3.12.10"
PYTHON_SERIES="${PYTHON_VERSION%.*}"
RUNTIME_DIR="$DIR/runtime/python"
BOOTSTRAP_PYTHON3="$RUNTIME_DIR/bin/python3"
BOOTSTRAP_PYTHON="$RUNTIME_DIR/bin/python"

find_python() {
    if [ -x "$DIR/.venv/bin/python3" ]; then
        printf '%s\n' "$DIR/.venv/bin/python3"
        return 0
    fi
    if [ -x "$DIR/.venv/Scripts/python.exe" ]; then
        printf '%s\n' "$DIR/.venv/Scripts/python.exe"
        return 0
    fi

    for candidate in \
        "$DIR/runtime/python/bin/python3" \
        "$DIR/runtime/python/bin/python" \
        "$DIR/runtime/python/python.exe" \
        "$DIR/runtime/python/Scripts/python.exe" \
        "$DIR/.runtime/python/bin/python3" \
        "$DIR/.runtime/python/bin/python" \
        "$DIR/.runtime/python/python.exe" \
        "$DIR/.runtime/python/Scripts/python.exe"
    do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return 0
    fi

    return 1
}

bootstrap_python() {
    if [ "$(uname -s)" != "Darwin" ]; then
        cat <<'EOF'
Bob couldn't find Python on this machine.

On macOS, run setup.sh from a connected machine so Bob can download Python automatically.
On other systems, use the platform-specific setup launcher.
EOF
        return 1
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "Bob needs curl to download Python automatically."
        return 1
    fi

    PKG_URL="https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-macos11.pkg"
    TMP_PKG="$(mktemp "/tmp/bob-python-${PYTHON_VERSION}.XXXXXX.pkg")"
    TMP_LOG="$(mktemp "/tmp/bob-python-install.${PYTHON_VERSION}.XXXXXX.log")"
    USER_PYTHON="$HOME/Library/Frameworks/Python.framework/Versions/$PYTHON_SERIES/bin/python3"
    SYSTEM_PYTHON="/Library/Frameworks/Python.framework/Versions/$PYTHON_SERIES/bin/python3"

    echo "Bob couldn't find Python. Downloading Python $PYTHON_VERSION from python.org..."
    if ! curl --fail --location --silent --show-error "$PKG_URL" --output "$TMP_PKG"; then
        echo "Bob couldn't download Python automatically."
        rm -f "$TMP_PKG" "$TMP_LOG"
        return 1
    fi

    echo "Installing a local Python runtime for Bob..."
    if ! installer -pkg "$TMP_PKG" -target CurrentUserHomeDirectory >"$TMP_LOG" 2>&1; then
        cat <<EOF
Bob downloaded Python but couldn't install it automatically.

Installer log: $TMP_LOG
EOF
        rm -f "$TMP_PKG"
        return 1
    fi

    rm -f "$TMP_PKG"
    mkdir -p "$RUNTIME_DIR/bin"

    if [ -x "$USER_PYTHON" ]; then
        ln -sfn "$USER_PYTHON" "$BOOTSTRAP_PYTHON3"
        ln -sfn "$USER_PYTHON" "$BOOTSTRAP_PYTHON"
        return 0
    fi

    if [ -x "$SYSTEM_PYTHON" ]; then
        ln -sfn "$SYSTEM_PYTHON" "$BOOTSTRAP_PYTHON3"
        ln -sfn "$SYSTEM_PYTHON" "$BOOTSTRAP_PYTHON"
        return 0
    fi

    cat <<EOF
Bob installed Python but couldn't find the interpreter afterward.

Expected one of:
  $USER_PYTHON
  $SYSTEM_PYTHON
EOF
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    bootstrap_python
    PYTHON="$(find_python || true)"
fi

if [ -z "$PYTHON" ]; then
    echo "Bob still couldn't find a usable Python runtime."
    exit 1
fi

if [ "$#" -gt 0 ]; then
    exec "$PYTHON" "$DIR/lib/datapull.py" "$@"
fi

exec "$PYTHON" "$DIR/lib/datapull.py" onboard --interactive
