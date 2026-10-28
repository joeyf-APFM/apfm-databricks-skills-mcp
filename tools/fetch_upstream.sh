#!/usr/bin/env bash
set -euo pipefail
# Usage: tools/fetch_upstream.sh DEST_DIR
cd "$(dirname "$0")/.."
git clone --depth 1 --branch "$(cat upstream.lock)" https://github.com/databricks/databricks-agent-skills "$1"
