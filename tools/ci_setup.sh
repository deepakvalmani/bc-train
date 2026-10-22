#!/usr/bin/env bash
# Linux runtime for CI / WSL / Colab: installs the cambc CLI, creates the workspace in ./rt and adds the map pool.
# Afterwards run tools with:  export CAMBC_HOME=rt
set -euo pipefail
python3 -m pip install --quiet --upgrade cambc || python3 -m pip install --quiet --upgrade --break-system-packages cambc
CB="$(command -v cambc)"
mkdir -p rt
cd rt
cambc init --yes . >/dev/null
mkdir -p maps bots
cp ../maps_pool/*.map26a maps/
cp "$CB" ./cambc 2>/dev/null || true
chmod +x ./cambc
./cambc --version
ls maps | wc -l
