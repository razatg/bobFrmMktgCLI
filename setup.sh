#!/bin/bash
# Bob Frm Mktg — compatibility setup launcher

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    cat <<'EOF'
Bob can't start because this folder does not include a Python runtime.

Use the full Bob release package for your computer, then open that folder in your AI app and say: set me up
EOF
    exit 1
fi

exec "$PYTHON" "$DIR/lib/datapull.py" onboard --interactive
