#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "ReelsFactoryPro - Instalación"
echo "Usa ./run.sh como entrypoint único (instala dependencias y arranca)."

chmod +x ./run.sh 2>/dev/null || true
exec ./run.sh
