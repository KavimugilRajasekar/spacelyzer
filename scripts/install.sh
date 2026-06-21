#!/bin/sh
set -e

echo "Installing Spacelyzer..."

# 1. Check for Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but not found on your system." >&2
    exit 1
fi

# 2. Setup directory structure
SPACELYZER_DIR="$HOME/.spacelyzer"
BIN_DIR="$SPACELYZER_DIR/bin"
REPO_DIR="$SPACELYZER_DIR/repo"

mkdir -p "$BIN_DIR"

# 3. Download/clone the source code
if command -v git >/dev/null 2>&1; then
    if [ -d "$REPO_DIR" ]; then
        echo "Updating existing repository..."
        cd "$REPO_DIR" && git pull --quiet
    else
        echo "Cloning Spacelyzer repository..."
        git clone --quiet "https://github.com/KavimugilRajasekar/spacelyzer.git" "$REPO_DIR"
    fi
else
    echo "git not found. Downloading repository archive..."
    rm -rf "$REPO_DIR"
    mkdir -p "$REPO_DIR"
    curl -fsSL "https://github.com/KavimugilRajasekar/spacelyzer/archive/refs/heads/main.tar.gz" | tar -xz -C "$REPO_DIR" --strip-components=1
fi

# 4. Create runner script
echo "Creating launcher script..."
cat << 'EOF' > "$BIN_DIR/spacelyzer"
#!/bin/sh
# Launcher for Spacelyzer
export PYTHONPATH="$HOME/.spacelyzer/repo:$PYTHONPATH"
exec python3 -m spacelyzer.cli "$@"
EOF

chmod +x "$BIN_DIR/spacelyzer"

# 5. Add to PATH
SHELL_CONFIGS="$HOME/.bashrc $HOME/.zshrc $HOME/.profile $HOME/.bash_profile"
PATH_ADDED=false
EXPORT_LINE="export PATH=\"\$HOME/.spacelyzer/bin:\$PATH\""

for config in $SHELL_CONFIGS; do
    if [ -f "$config" ]; then
        if ! grep -q ".spacelyzer/bin" "$config"; then
            echo "" >> "$config"
            echo "# Spacelyzer path configuration" >> "$config"
            echo "$EXPORT_LINE" >> "$config"
            echo "Added Spacelyzer to $config"
            PATH_ADDED=true
        fi
    fi
done

echo "Verification:"
"$BIN_DIR/spacelyzer" --version

echo ""
echo "Installation complete!"
if [ "$PATH_ADDED" = true ]; then
    echo "Please restart your terminal or run: source ~/.bashrc (or ~/.zshrc) to start using 'spacelyzer'"
else
    echo "You can run 'spacelyzer' directly using: $BIN_DIR/spacelyzer"
fi
