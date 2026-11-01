#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INTEGRATION="$ROOT/source/integration"
BASELINE="$INTEGRATION/artifacts/duckdb-v1.4.0-baseline"
OUT="$INTEGRATION/duckdb_topk_operator_profile"

g++ -std=c++17 -O3 -DNDEBUG \
    -I "$INTEGRATION/duckdb-v1.4.0/src/include" \
    "$INTEGRATION/duckdb_topk_operator_profile.cpp" \
    -L "$BASELINE" -Wl,-rpath,"$BASELINE" -lduckdb \
    -o "$OUT"

printf 'built %s\n' "$OUT"
ldd "$OUT" | grep libduckdb
