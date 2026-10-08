#!/bin/sh
# Unpack the latest big-test export (bigtest branch, refreshed once a day at the 06 UTC scan) into <out_dir>.
# usage, from the repository root:  sh research/get_data.sh /some/scratch/dir/data
set -e
out=${1:?usage: sh research/get_data.sh <out_dir>}
mkdir -p "$out"
git fetch -q origin bigtest
git log -1 --format='bigtest export: %h %ci %s' origin/bigtest
git archive origin/bigtest | tar -x -C "$out"
if ls "$out"/memesnapres.tgz.part-* >/dev/null 2>&1; then
  cat "$out"/memesnapres.tgz.part-* | tar -xz -C "$out"
elif [ -f "$out/memesnapres.tgz" ]; then
  tar -xzf "$out/memesnapres.tgz" -C "$out"
fi
echo "$(ls "$out/memesnapres" | wc -l) scored snapshot chunks in $out/memesnapres"
