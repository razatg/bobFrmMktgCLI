#!/bin/bash
# Bob Frm Mktg — compatibility setup launcher

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 &>/dev/null; then
    echo "Python 3 is not installed."
    echo ""
    echo "Install Python 3 first, then open this folder in your AI app and say: set me up"
    echo "Download: https://www.python.org/downloads/"
    exit 1
fi

python3 "$DIR/lib/datapull.py" onboard
