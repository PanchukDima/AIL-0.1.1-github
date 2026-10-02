#!/bin/sh
set -eu
AIL_SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AIL_PYTHON=${AIL_PYTHON:-python3}
exec "$AIL_PYTHON" -B "$AIL_SOURCE_DIR/scripts/install.py" --uninstall "$@"
