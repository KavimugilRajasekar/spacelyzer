#!/bin/sh
# Spacelyzer installer for macOS / Linux
set -e

echo "Installing Spacelyzer..."

# ------------------------------------------------------------------ #
# 1. Check for Python 3.8+
# ------------------------------------------------------------------ #
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" > /dev/null 2>&1; then
        # Verify it is at least 3.8
        ok=$("$cmd" -c "import sys; print('ok' if sys.version_info >= (3,8) else 'old')" 2>/dev/null || true)
        if [ "$ok" = "ok" ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "Error: Python 3.8 or newer is required but was not found." >&2
    echo "       Install it from https://www.python.org/downloads/ and re-run." >&2
    exit 1
fi

echo "  Python found: $PYTHON_CMD"

# ------------------------------------------------------------------ #
# 2. Setup directory structure
# ------------------------------------------------------------------ #
SPACELYZER_DIR="$HOME/.spacelyzer"
BIN_DIR="$SPACELYZER_DIR/bin"
REPO_DIR="$SPACELYZER_DIR/repo"
SNAPSHOTS_DIR="$SPACELYZER_DIR/snapshots"

mkdir -p "$BIN_DIR" "$SNAPSHOTS_DIR"

# ------------------------------------------------------------------ #
# 3. Download / update the source code
# ------------------------------------------------------------------ #
if command -v git > /dev/null 2>&1; then
    if [ -d "$REPO_DIR" ]; then
        echo "Updating existing repository..."
        # Use git -C so we never mutate the shell's working directory
        if ! git -C "$REPO_DIR" pull --quiet; then
            echo "Error: git pull failed. Check your internet connection." >&2
            exit 1
        fi
    else
        echo "Cloning Spacelyzer repository..."
        if ! git clone --quiet "https://github.com/KavimugilRajasekar/spacelyzer.git" "$REPO_DIR"; then
            echo "Error: git clone failed. Check your internet connection." >&2
            exit 1
        fi
    fi
else
    echo "git not found. Downloading repository archive via curl..."
    rm -rf "$REPO_DIR"
    mkdir -p "$REPO_DIR"
    ARCHIVE_URL="https://github.com/KavimugilRajasekar/spacelyzer/archive/refs/heads/main.tar.gz"
    if command -v curl > /dev/null 2>&1; then
        if ! curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$REPO_DIR" --strip-components=1; then
            echo "Error: Download or extraction failed. Check your internet connection." >&2
            exit 1
        fi
    elif command -v wget > /dev/null 2>&1; then
        TMP_ARCHIVE="$SPACELYZER_DIR/repo.tar.gz"
        if ! wget -qO "$TMP_ARCHIVE" "$ARCHIVE_URL"; then
            echo "Error: Download failed. Check your internet connection." >&2
            exit 1
        fi
        tar -xz -C "$REPO_DIR" --strip-components=1 -f "$TMP_ARCHIVE"
        rm -f "$TMP_ARCHIVE"
    else
        echo "Error: Neither git, curl, nor wget is available. Install one and retry." >&2
        exit 1
    fi
fi

# Sanity-check: ensure the package is present in the downloaded repo
if [ ! -f "$REPO_DIR/spacelyzer/__init__.py" ]; then
    echo "Error: Repository structure looks wrong — spacelyzer package not found." >&2
    exit 1
fi

# ------------------------------------------------------------------ #
# 4. Create the launcher script
# ------------------------------------------------------------------ #
echo "Creating launcher script..."
# Use single-quoted heredoc so $HOME / $@ are written literally and
# resolved at run-time (not at install time).
cat << 'LAUNCHER' > "$BIN_DIR/spacelyzer"
#!/bin/sh
export PYTHONPATH="$HOME/.spacelyzer/repo:$PYTHONPATH"
exec python3 -m spacelyzer "$@"
LAUNCHER

chmod +x "$BIN_DIR/spacelyzer"

# ------------------------------------------------------------------ #
# 5. Add the bin directory to PATH in shell config files
# ------------------------------------------------------------------ #
EXPORT_LINE="export PATH=\"\$HOME/.spacelyzer/bin:\$PATH\""
PATH_ADDED=false

for config in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile"; do
    if [ -f "$config" ]; then
        if ! grep -q ".spacelyzer/bin" "$config"; then
            printf '\n# Spacelyzer\n%s\n' "$EXPORT_LINE" >> "$config"
            echo "  Added PATH entry to $config"
            PATH_ADDED=true
        fi
    fi
done

# Also update the current session so the verification below works
export PATH="$BIN_DIR:$PATH"

# ------------------------------------------------------------------ #
# 6. Verification
# ------------------------------------------------------------------ #
echo ""
echo "Verification:"
if ! "$BIN_DIR/spacelyzer" --version; then
    echo "Error: Verification failed. Try running: $BIN_DIR/spacelyzer --version" >&2
    exit 1
fi

echo ""
echo "Installation complete!"
if [ "$PATH_ADDED" = "true" ]; then
    echo "Restart your terminal or run:  source ~/.bashrc  (or ~/.zshrc)"
else
    echo "Run spacelyzer directly with:  $BIN_DIR/spacelyzer"
fi
echo "Snapshots are stored in:  $SNAPSHOTS_DIR"
