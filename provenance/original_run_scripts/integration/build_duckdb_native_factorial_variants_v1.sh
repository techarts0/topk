#!/usr/bin/env bash
set -euo pipefail
ROOT=*
SRC="$ROOT/source/integration/duckdb-v1.4.0/src/execution/operator/order/physical_top_n.cpp"
VAR="$ROOT/source/integration/native-factorial-variants-v1.0"
BUILD="$ROOT/source/integration/build-baseline"
ART="$ROOT/source/integration/artifacts"
COMBINED="$VAR/physical_top_n.combined.cpp"
restore_source() {
  cp "$COMBINED" "$SRC"
}
trap restore_source EXIT

if [[ "$(sha256sum "$SRC" | awk '{print $1}')" != "bd1be875696593b66a57d5ae14f17db158b28d08f91f1fe7bf1bbd5a110254bc" ]]; then
  echo "source does not match frozen combined treatment" >&2
  exit 2
fi

for variant in heap_avx2 array_scalar; do
  out="$ART/duckdb-v1.4.0-$variant"
  if [[ -e "$out" ]]; then
    echo "refusing to overwrite existing library artifact: $out" >&2
    exit 2
  fi
  cp "$VAR/physical_top_n.$variant.cpp" "$SRC"
  make -C "$BUILD" duckdb -j8
  mkdir -p "$out"
  cp "$BUILD/src/libduckdb.so.1.4.0" "$out/libduckdb.so"
  cp "$BUILD/src/libduckdb.so.1.4.0" "$out/libduckdb.so.1.4"
  sha256sum "$out/libduckdb.so.1.4"
done

restore_source
make -C "$BUILD" duckdb -j8

