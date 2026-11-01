#!/usr/bin/env bash
set -euo pipefail
ROOT=*
SRC="$ROOT/source/integration/duckdb-v1.4.0/src/execution/operator/order/physical_top_n.cpp"
VAR="$ROOT/source/integration/filter-attribution-v1.0"
BASE="$ROOT/source/integration/native-factorial-variants-v1.0/physical_top_n.heap_avx2.cpp"
SCALAR="$VAR/physical_top_n.heap_scalar_specialized.cpp"
BUILD="$ROOT/source/integration/build-baseline"
ART="$ROOT/source/integration/artifacts/duckdb-v1.4.0-heap_scalar_specialized"
OUT="$ROOT/source/integration/filter-attribution-v1.0/build-artifacts"
mkdir -p "$OUT/build"
if [[ -e "$ART" || -e "$OUT/run_manifest.json" ]]; then echo "refusing to overwrite attribution artifacts" >&2; exit 2; fi
if [[ "$(sha256sum "$BASE" | awk '{print $1}')" != "1f6615a6081870e5063366f5c7fa6344c7de9ddcdc4efb969af2288dae23509d" ]]; then echo "frozen heap AVX2 source hash mismatch" >&2; exit 2; fi
cp "$SRC" "$OUT/build/physical_top_n.original_source.cpp"
restore() {
  cp "$OUT/build/physical_top_n.original_source.cpp" "$SRC"
  make -C "$BUILD" duckdb -j8 > "$OUT/build/restore_combined_build.log" 2>&1 || echo "WARNING: restoring build tree failed; source file was restored" >&2
}
trap restore EXIT
cp "$SCALAR" "$SRC"
if ! make -C "$BUILD" duckdb -j8 > "$OUT/build/scalar_specialized_build.log" 2>&1; then tail -n 100 "$OUT/build/scalar_specialized_build.log" >&2; exit 1; fi
mkdir -p "$ART"
cp "$BUILD/src/libduckdb.so.1.4.0" "$ART/libduckdb.so"
cp "$BUILD/src/libduckdb.so.1.4.0" "$ART/libduckdb.so.1.4"
OBJ="$BUILD/src/execution/operator/order/CMakeFiles/duckdb_operator_order.dir/ub_duckdb_operator_order.cpp.o"
cp "$OBJ" "$OUT/build/scalar_specialized_unity.o"
cp "$BUILD/src/libduckdb.so.1.4.0" "$OUT/build/libduckdb_scalar_specialized.so"
sha256sum "$SCALAR" "$ART/libduckdb.so.1.4" "$OUT/build/scalar_specialized_unity.o" > "$OUT/build/scalar_hashes.txt"
echo "Scalar specialized library and build object archived. Run build_diagnostics.sh separately for vectorizer diagnostics and disassembly."
