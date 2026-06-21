#!/bin/sh
set -e

echo "Uninstalling Spacelyzer..."

SPACELYZER_DIR="$HOME/.spacelyzer"

# Remove directory
if [ -d "$SPACELYZER_DIR" ]; then
    rm -rf "$SPACELYZER_DIR"
    echo "Removed $SPACELYZER_DIR"
fi

# Clean up PATH configurations
SHELL_CONFIGS="$HOME/.bashrc $HOME/.zshrc $HOME/.profile $HOME/.bash_profile"

for config in $SHELL_CONFIGS; do
    if [ -f "$config" ]; then
        if grep -q ".spacelyzer/bin" "$config"; then
            # Use sed to remove the added line block
            # Create a temporary file and replace
            temp_file=$(mktemp)
            grep -v ".spacelyzer/bin" "$config" | grep -v "# Spacelyzer path configuration" > "$temp_file" || true
            mv "$temp_file" "$config"
            echo "Removed path configuration from $config"
        fi
    fi
done

echo "Uninstallation complete!"
