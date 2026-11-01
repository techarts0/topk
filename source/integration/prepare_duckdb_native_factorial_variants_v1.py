#!/usr/bin/env python3
"""Derive native DuckDB factorial ablations from the frozen combined patch."""
from pathlib import Path
import hashlib
import shutil

ROOT = Path(__file__).resolve().parents[2]
REPO_FILE = ROOT / "source/integration/duckdb-v1.4.0/src/execution/operator/order/physical_top_n.cpp"
OUT = ROOT / "source/integration/native-factorial-variants-v1.0"
EXPECTED_COMBINED_SHA256 = "bd1be875696593b66a57d5ae14f17db158b28d08f91f1fe7bf1bbd5a110254bc"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one matching snippet, got {count}")
    return text.replace(old, new, 1)


def main():
    original_bytes = REPO_FILE.read_bytes()
    if sha(original_bytes) != EXPECTED_COMBINED_SHA256:
        raise RuntimeError("DuckDB source does not match frozen combined treatment; refusing to derive variants")
    OUT.mkdir(exist_ok=True)
    combined = OUT / "physical_top_n.combined.cpp"
    if combined.exists() and combined.read_bytes() != original_bytes:
        raise RuntimeError("existing combined-source snapshot differs; refusing to overwrite")
    combined.write_bytes(original_bytes)
    base = original_bytes.decode("utf-8").replace("\r\n", "\n")

    # Heap + AVX2: remove only the array-maintenance changes. Keep the guarded AVX2 filter.
    heap_avx = base
    method = """\tinline bool UseSmallSortedArray() const {
\t\treturn heap_size > 0 && heap_size <= 100 && offset == 0 && orders.size() == 1 &&
\t\t       orders[0].expression->return_type == LogicalType::DOUBLE && orders[0].type == OrderType::DESCENDING;
\t}

"""
    heap_avx = replace_once(heap_avx, method, "", "remove sorted-array predicate")
    heap_avx = replace_once(
        heap_avx,
        """\t\tconst auto &worst_entry = UseSmallSortedArray() ? heap.back() : heap.front();
\t\tif (sort_key < worst_entry.sort_key) {""",
        """\t\tif (sort_key < heap.front().sort_key) {""",
        "restore heap boundary",
    )
    heap_avx = replace_once(
        heap_avx,
        """\t\tif (UseSmallSortedArray()) {
\t\t\tif (heap.size() >= heap_size) {
\t\t\t\theap.pop_back();
\t\t\t}
\t\t\tauto insert_position = std::lower_bound(heap.begin(), heap.end(), entry);
\t\t\theap.insert(insert_position, entry);
\t\t\treturn;
\t\t}
""",
        "",
        "remove sorted-array insertion",
    )
    heap_avx = replace_once(
        heap_avx,
        "global_boundary->UpdateValue(UseSmallSortedArray() ? heap.back().sort_key : heap.front().sort_key);",
        "global_boundary->UpdateValue(heap.front().sort_key);",
        "restore heap global boundary",
    )
    heap_avx = replace_once(
        heap_avx,
        """if (has_avx2 && UseSmallSortedArray() && orders[0].null_order == OrderByNullType::NULLS_LAST &&
""",
        """if (has_avx2 && heap_size > 0 && heap_size <= 100 && offset == 0 && orders.size() == 1 &&
\t    orders[0].expression->return_type == LogicalType::DOUBLE && orders[0].type == OrderType::DESCENDING &&
\t    orders[0].null_order == OrderByNullType::NULLS_LAST &&
""",
        "make AVX2 eligibility independent of representation",
    )
    (OUT / "physical_top_n.heap_avx2.cpp").write_text(heap_avx, encoding="utf-8", newline="\n")

    # Array + stock filter: remove AVX2 code while keeping all sorted-array state changes.
    array_scalar = base
    array_scalar = replace_once(array_scalar, "#include <cmath>\n", "", "remove math include")
    preamble_start = array_scalar.index("#if defined(__x86_64__) && (defined(__GNUC__) || defined(__clang__))")
    preamble_end = array_scalar.index("#endif", preamble_start) + len("#endif\n")
    array_scalar = array_scalar[:preamble_start] + array_scalar[preamble_end:]
    helper_start = array_scalar.index("#if defined(DUCKDB_TOPN_CAN_COMPILE_AVX2)")
    helper_end = array_scalar.index("#endif", helper_start) + len("#endif\n")
    array_scalar = array_scalar[:helper_start] + array_scalar[helper_end:]
    hot_comment = "// Specialized hot path for the audited single-key DOUBLE DESC NULLS LAST case."
    hot_start = array_scalar.index(hot_comment)
    guard_start = array_scalar.rfind("#if defined(DUCKDB_TOPN_CAN_COMPILE_AVX2)", 0, hot_start)
    hot_end = array_scalar.index("#endif", hot_start) + len("#endif\n")
    if guard_start < 0:
        raise RuntimeError("could not locate AVX2 boundary-filter block")
    array_scalar = array_scalar[:guard_start] + array_scalar[hot_end:]
    if "DUCKDB_TOPN_CAN_COMPILE_AVX2" in array_scalar or "TopNAVX2FilterGreater" in array_scalar:
        raise RuntimeError("AVX2 code remains in array-scalar variant")
    if "UseSmallSortedArray()" not in array_scalar:
        raise RuntimeError("array-scalar variant lost sorted-array treatment")
    (OUT / "physical_top_n.array_scalar.cpp").write_text(array_scalar, encoding="utf-8", newline="\n")

    # Hashes and the exact diffs from the combined source are convenient build provenance.
    manifest = [
        "Derived from DuckDB v1.4.0 combined treatment source.",
        f"combined_sha256={sha(original_bytes)}",
        f"heap_avx2_sha256={sha((OUT / 'physical_top_n.heap_avx2.cpp').read_bytes())}",
        f"array_scalar_sha256={sha((OUT / 'physical_top_n.array_scalar.cpp').read_bytes())}",
    ]
    (OUT / "variant_source_hashes.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print("\n".join(manifest))


if __name__ == "__main__":
    main()
