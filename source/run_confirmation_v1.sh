#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
out="results/confirm-v1"
mkdir -p "$out"
sha256sum CONFIRMATION_PLAN_v1.0.md bench.cpp kernels.hpp build/topk_bench run_pilot.py run_confirmation_v1.sh > "$out/frozen_hashes.sha256"
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$out/start_utc.txt"
items=(
  'uniform_1000000_s45.csv uniform 100 202610250'
  'normal_1000000_s43.csv normal 100 202610251'
  'pareto_1000000_s44.csv pareto 100 202610252'
  'nyc_yellow_2024_01_distance_chrono_1000000.csv taxi 100 202610253'
  'uniform_1000000_s45.csv uniform 10000 202610254'
  'normal_1000000_s43.csv normal 10000 202610255'
  'pareto_1000000_s44.csv pareto 10000 202610256'
  'nyc_yellow_2024_01_distance_chrono_1000000.csv taxi 10000 202610257'
)
for item in "${items[@]}"; do
  read -r file label k seed <<< "$item"
  python3 run_pilot.py "data/$file" --k "$k" --blocks 25 --reps 5 --seed "$seed" --cpu 2 \
    --status confirmatory --out "$out/$label-k$k"
done
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$out/stop_utc.txt"
sha256sum "$out"/*/environment.json "$out"/*/timings.csv > "$out/result_hashes.sha256"
