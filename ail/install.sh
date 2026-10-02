#!/bin/sh
# Install from a local source tree. No download, pip or privileged write.
set -eu
AIL_SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AIL_PYTHON=${AIL_PYTHON:-python3}
if ! command -v "$AIL_PYTHON" >/dev/null 2>&1; then
    printf '%s\n' 'AIL requires Python 3.10+. Install python3 first.' >&2
    exit 2
fi
exec "$AIL_PYTHON" -B "$AIL_SOURCE_DIR/scripts/install.py" "$@"
