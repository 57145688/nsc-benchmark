#!/usr/bin/env bash
# Build and solve one OpenFOAM case.
#   run_foam_wsl.sh [case-dir] [restart]
#
# OpenFOAM refuses paths that contain spaces, so the generated case (which
# lives under "trae workspace") is copied to $HOME/nsc_case, solved there and
# the logs + time directories are copied back.  With "restart" as the second
# argument the latest fields of the previous run are used as the initial
# state, which is what the coupled iterations need.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CASE="${1:-results/foam/case}"
RESTART="${2:-}"
WORK="${NSC_WORK:-$HOME/nsc_case}"

export WM_PROJECT_DIR=/usr/share/openfoam

LATEST=""
if [ "$RESTART" = "restart" ] && [ -d "$WORK" ]; then
    LATEST="$(ls -d "$WORK"/[0-9]* 2>/dev/null | sort -g | tail -1)"
fi

rm -rf "$WORK"
mkdir -p "$WORK"
cp -r "$ROOT/$CASE/." "$WORK/"
cd "$WORK"
# Time directories copied back from an earlier run must not survive: they would
# be newer than this run's writes and fool the post-processor.
for stale in [0-9]*; do
    if [ -d "$stale" ] && [ "$stale" != "0" ]; then
        rm -rf "$stale"
    fi
done

for tool in blockMesh topoSet setFields checkMesh; do
    if ! "$tool" > "log.$tool" 2>&1; then
        tail -30 "log.$tool"
        exit 1
    fi
done

if [ -n "$LATEST" ]; then
    for field in T U p_rgh alphat nut; do
        if [ -f "$LATEST/$field" ]; then
            cp "$LATEST/$field" "0/$field"
        fi
    done
fi

if ! buoyantBoussinesqPimpleFoam > log.solver 2>&1; then
    tail -40 log.solver
    exit 1
fi
tail -25 log.solver

mkdir -p "$ROOT/$CASE"
cp log.* "$ROOT/$CASE/" 2>/dev/null || true
for time_dir in [0-9]*; do
    if [ -d "$time_dir" ] && [ "$time_dir" != "0" ]; then
        cp -r "$time_dir" "$ROOT/$CASE/"
    fi
done
