#!/bin/bash
# Install claude-continue as an iTerm2 AutoLaunch script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ITERM_SCRIPTS_DIR="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"

echo "=== Claude Continue Installer ==="
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "ERROR: This daemon only works on macOS with iTerm2."
    exit 1
fi

# Check if iTerm2 is installed
if [[ ! -d "/Applications/iTerm.app" ]]; then
    echo "ERROR: iTerm2 is not installed."
    echo "Please install iTerm2 from https://iterm2.com/"
    exit 1
fi

# Create AutoLaunch directory if it doesn't exist
echo "Creating iTerm2 AutoLaunch directory..."
mkdir -p "$ITERM_SCRIPTS_DIR"

# Create symlink to project
LINK_PATH="$ITERM_SCRIPTS_DIR/claude-continue"
if [[ -L "$LINK_PATH" ]]; then
    echo "Removing existing symlink..."
    rm "$LINK_PATH"
elif [[ -d "$LINK_PATH" ]]; then
    echo "Removing existing directory..."
    rm -rf "$LINK_PATH"
fi

echo "Creating symlink to $PROJECT_DIR..."
ln -s "$PROJECT_DIR" "$LINK_PATH"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
cd "$PROJECT_DIR"
if [[ -d "venv" ]]; then
    source venv/bin/activate
else
    python3 -m venv venv
    source venv/bin/activate
fi
pip install -r requirements.txt

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "1. Open iTerm2 Preferences (Cmd+,)"
echo "2. Go to 'General' > 'Magic'"
echo "3. Enable 'Enable Python API'"
echo "4. Restart iTerm2"
echo ""
echo "The daemon will automatically start when iTerm2 launches."
echo "To test now, run: python $PROJECT_DIR/src/daemon.py --test"
