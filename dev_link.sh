#!/bin/bash

# Blender 4.2+ local development setup script
# This script symlinks your local source code directly into Blender's extension folder
# so you NEVER have to build or install a ZIP file during development.

# Adjust this if you are using a different Blender version
BLENDER_VERSION="5.2"

EXT_DIR="$HOME/Library/Application Support/Blender/${BLENDER_VERSION}/extensions/user_default/blender_agent_terminal"

echo "Setting up Blender Agent Terminal for live development..."

# 1. Remove any installed version (the unpacked zip)
if [ -d "$EXT_DIR" ] || [ -L "$EXT_DIR" ]; then
    echo "Removing existing extension installation at $EXT_DIR"
    rm -rf "$EXT_DIR"
fi

# 2. Create the parent directories if they don't exist
mkdir -p "$(dirname "$EXT_DIR")"

# 3. Create a symbolic link from the Blender extensions folder directly to this source code
echo "Creating symlink..."
ln -s "$(pwd)" "$EXT_DIR"

echo "✅ Done! Your source code is now linked directly to Blender."
echo "Any changes you make in this directory will instantly appear in Blender."
echo "To apply code changes in Blender, just uncheck and re-check the add-on in Preferences,"
echo "or search for 'Reload Scripts' (F3) in Blender."
