#!/usr/bin/env bash
set -euo pipefail
ROOT=*
BUILD="$ROOT/source/integration/build-baseline"
OUT="$ROOT/source/integration/filter-attribution-v1.0/build-artifacts/build"
SCALAR="$ROOT/source/integration/filter-attribution-v1.0/physical_top_n.heap_scalar_specialized.cpp"
AVX="$ROOT/source/integration/native-factorial-variants-v1.0/physical_top_n.heap_avx2.cpp"
UNITY="$BUILD/src/execution/operator/order/ub_duckdb_operator_order.cpp"
FLAGS="$BUILD/src/execution/operator/order/CMakeFiles/duckdb_operator_order.dir/flags.make"
mkdir -p "$OUT"
CXX_DEFINES="$(sed -n 's/^CXX_DEFINES = //p' "$FLAGS")"
CXX_INCLUDES="$(sed -n 's/^CXX_INCLUDES = //p' "$FLAGS")"
CXX_FLAGS="$(sed -n 's/^CXX_FLAGS = //p' "$FLAGS")"
for cell in scalar avx2; do
  if [[ "$cell" == scalar ]]; then SRC_VARIANT="$SCALAR"; else SRC_VARIANT="$AVX"; fi
  sed "s#${ROOT}/source/integration/duckdb-v1.4.0/src/execution/operator/order/physical_top_n.cpp#${SRC_VARIANT}#" "$UNITY" > "$OUT/ub_${cell}_diagnostic.cpp"
  /usr/bin/c++ $CXX_DEFINES $CXX_INCLUDES $CXX_FLAGS -fopt-info-vec-all="$OUT/gcc_${cell}_vectorization_report.txt" -c "$OUT/ub_${cell}_diagnostic.cpp" -o "$OUT/${cell}_diagnostic.o" 2> "$OUT/gcc_${cell}_compile.stderr.txt"
  objdump -d -C "$OUT/${cell}_diagnostic.o" > "$OUT/${cell}_diagnostic.disassembly.txt"
  nm -C "$OUT/${cell}_diagnostic.o" > "$OUT/${cell}_diagnostic.symbols.txt"
done
sha256sum "$SCALAR" "$AVX" "$ROOT/source/integration/artifacts/duckdb-v1.4.0-heap_scalar_specialized/libduckdb.so.1.4" "$OUT/scalar_diagnostic.o" "$OUT/avx2_diagnostic.o" > "$OUT/codegen_hashes.txt"
