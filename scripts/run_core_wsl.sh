#!/usr/bin/env bash
# Run the OpenMC core from WSL.  Override OPENMC_CROSS_SECTIONS or
# OPENMC_PYTHON if your installation lives somewhere else.
set -euo pipefail
cd "$(dirname "$0")/.."
export OPENMC_CROSS_SECTIONS="${OPENMC_CROSS_SECTIONS:-/mnt/e/trae/trae workspace/OPENMC/_data/nndc_hdf5/cross_sections.xml}"
export PATH="/home/xander/openmc-env/bin:${PATH}"
exec "${OPENMC_PYTHON:-/home/xander/openmc-env/bin/python}" scripts/run_core.py "$@"
