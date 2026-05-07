#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $(basename "$0") <chrome-extension-id>"
    echo ""
    echo "Find the extension ID at chrome://extensions after loading the unpacked extension."
    exit 1
fi

EXT_ID="$1"
HOST_NAME="com.shayelkin.sync_safari_bookmarks"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"

mkdir -p "$MANIFEST_DIR"

cat > "$MANIFEST_DIR/$HOST_NAME.json" <<EOF
{
  "name": "$HOST_NAME",
  "description": "Sync bookmarks between Chrome and Safari",
  "path": "$PROJECT_DIR/host/run.sh",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXT_ID/"]
}
EOF

chmod +x "$PROJECT_DIR/host/run.sh"
echo "Installed native messaging host manifest at:"
echo "  $MANIFEST_DIR/$HOST_NAME.json"
echo ""
echo "Extension ID: $EXT_ID"
