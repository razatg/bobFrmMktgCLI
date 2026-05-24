#!/bin/bash
# Bob Frm Mktg — first-time setup
# Run once after cloning: bash setup.sh

set -e

echo ""
echo "Setting up Bob Frm Mktg..."
echo ""

# ── 1. Check for Python 3 ────────────────────────────────────────────────────

if command -v python3 &>/dev/null; then
    PYTHON_VER=$(python3 --version 2>&1)
    echo "✓ $PYTHON_VER found"
else
    echo "Python 3 is not installed."
    echo ""

    if command -v brew &>/dev/null; then
        echo "Installing Python via Homebrew (this may take a minute)..."
        brew install python3
    else
        echo "You need to install Python 3 first. Two options:"
        echo ""
        echo "  Option A — Homebrew (recommended for Mac):"
        echo "    1. Open Terminal and paste:"
        echo "       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    2. Once Homebrew is installed, run:  brew install python3"
        echo "    3. Run this script again:  bash setup.sh"
        echo ""
        echo "  Option B — Direct download:"
        echo "    Go to https://www.python.org/downloads/ and install the latest version."
        echo "    Then run this script again:  bash setup.sh"
        echo ""
        exit 1
    fi
fi

# ── 2. Create a virtual environment ─────────────────────────────────────────

if [ ! -d ".venv" ]; then
    echo "Creating isolated Python environment..."
    python3 -m venv .venv
    echo "✓ Environment created"
else
    echo "✓ Existing environment found"
fi

# ── 3. Install dependencies ──────────────────────────────────────────────────

echo "Installing dependencies (this may take a minute)..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "✓ Dependencies installed"

# ── 4. Create a bob launcher in the project root ────────────────────────────

cat > bob <<'EOF'
#!/bin/bash
# bob — convenience launcher that uses the project's virtual environment
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/.venv/bin/python3" "$DIR/lib/datapull.py" "$@"
EOF
chmod +x bob
echo "✓ bob launcher created"

echo ""
echo "────────────────────────────────────────"
echo "Setup complete. To get started:"
echo ""
echo "  ./bob onboard"
echo ""
echo "That will walk you through connecting your Google Ads account."
echo "────────────────────────────────────────"
echo ""
