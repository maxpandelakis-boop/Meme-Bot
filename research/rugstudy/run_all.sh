#!/bin/sh
# Rug and winner study (fake-money paper bot): rebuild every table from the results and bigtest branches. Reads data only, no network.
# usage, from the repository root:
#   sh research/rugstudy/run_all.sh <results db dir> <memesnapres dir> <out dir>
# PY (default python3) must have numpy; build.py and rugshape.py need the standard library only.
# The weights the radar uses (radar_weights.json) were frozen from the run of 2026-10-13. A new run writes
# <out dir>/radar_weights.json for review; it never overwrites the repository's file.
set -e
DB=${1:?usage: run_all.sh <results db dir> <memesnapres dir> <out dir>}
SNAP=${2:?usage: run_all.sh <results db dir> <memesnapres dir> <out dir>}
OUT=${3:?usage: run_all.sh <results db dir> <memesnapres dir> <out dir>}
D=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$D/../.." && pwd)
PY=${PY:-python3}
mkdir -p "$OUT"
python3 -I "$D/scripts/build.py" "$DB" "$SNAP" "$REPO" "$OUT" 2> "$OUT/build_stderr.txt"
$PY -I "$D/scripts/analyze.py" "$OUT" > /dev/null
$PY -I "$D/scripts/model.py" "$OUT" > /dev/null
for w in 15 10 6; do $PY -I "$D/scripts/staircase.py" "$DB" "$OUT" $w > /dev/null; done
$PY -I "$D/scripts/points.py" "$OUT" > /dev/null
$PY -I "$D/scripts/rules.py" "$OUT" > /dev/null
$PY -I "$D/scripts/young10.py" "$OUT" > /dev/null
$PY -I "$D/scripts/overlap.py" "$OUT" > /dev/null
$PY -I "$D/scripts/recommend.py" "$OUT" > /dev/null
$PY -I "$D/scripts/paper_pnl.py" "$OUT" > /dev/null
python3 -I "$D/scripts/rugshape.py" "$DB" "$OUT" > /dev/null
$PY -I "$D/scripts/unknown_mint.py" "$OUT" > /dev/null
$PY -I "$D/scripts/winpoints.py" "$OUT" > /dev/null
python3 -I "$D/make_weights.py" "$OUT" "$OUT/radar_weights.json"
echo done
