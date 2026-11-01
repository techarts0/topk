# DuckDB native Top-N factorial confirmation plan v1.0

Frozen before the factorial build and measurements: 2026-10-25 (Asia/Shanghai).

## Question

In DuckDB 1.4.0's eligible single-threaded TOP_N path, how do candidate representation and the boundary-filter implementation separately affect timing, and is there an interaction between them? This follows the earlier baseline-versus-joint-package confirmation; this new four-cell experiment is a separate confirmation and will not pool with the earlier run.

## Factorial cells

All builds use the same v1.4.0 commit, release configuration, query driver, data, plan, and runtime protocol.

| Cell | Candidate maintenance | Boundary filtering |
|---|---|---|
| heap_stock | DuckDB's original bounded min-heap | DuckDB's original per-chunk vector boundary filter |
| heap_avx2 | DuckDB's original bounded min-heap | guarded AVX2 specialization of the existing filter |
| array_stock | ascending contiguous candidate array | DuckDB's original per-chunk vector boundary filter |
| array_avx2 | ascending contiguous candidate array | guarded AVX2 specialization of the existing filter |

The AVX2 path is eligible only for the same guarded query/value cases used in the earlier treatment. The stock filter remains the baseline filter; we do not describe it as a scalar filter or assume it contains no compiler vectorization. The factorial compares the original DuckDB filter with the explicit AVX2 specialization.

## Correctness and plan gates

The query is SELECT score FROM topk_input ORDER BY score DESC LIMIT 100, threads=1. All variants must select the same TOP_N plan and produce identical output checksums for every paired block. The driver checks each timed query result against an in-memory full-sort reference. The edge suite runs against all four libraries and requires identical outputs for finite ties, distinct values, NaNs, NULL fallback, ASC, OFFSET, multiple keys, k=101 fallback, and parallel combine. Any correctness, checksum, plan, or build-identity mismatch stops confirmation.

## Workloads and protocol

Use the frozen dataset set from the preceding confirmation: ten seeds each for Uniform, Normal, and Pareto(alpha=2), N=1,000,000, plus the one fixed chronological NYC Yellow Taxi distance stream. The NYC stream is analyzed descriptively and is not pooled with IID seeds.

For each of 31 streams, run five independent process blocks. Randomize all four variant orders within each block using Python random seed 20261027. Pin each variant process to logical CPU 2. Each process creates a fresh in-memory database, performs one full-sort-checked warmup, and records three timed query-plus-complete-result-consumption calls. This yields 155 four-way blocks, 620 variant processes, and 1,860 timed calls. Keep every run, order, checksum, plan, stderr, and exit status. Do not discard or silently rerun adverse observations.

Measure user-mode cycles, instructions, branches, and branch misses in the same query-plus-fetch region using the grouped perf_event_open mechanism. Scale event values with enabled/running time and retain running percentages. Preserve raw values if events are unavailable or multiplexed; do not use an event below 95% running for mechanism claims.

## Prespecified effects and inference

For each IID population, calculate paired log-time ratios within each block, average blocks within seed, then give ten seeds equal weight. Ratios above one mean the numerator cell is faster.

The five contrasts are:
1. package: heap_stock / array_avx2;
2. AVX2 effect on heap: heap_stock / heap_avx2;
3. array effect with stock filtering: heap_stock / array_stock;
4. AVX2 effect on array: array_stock / array_avx2;
5. interaction: (array_stock / array_avx2) / (heap_stock / heap_avx2).

Resample seeds and then paired process blocks in 100,000 nested bootstrap replicates. There are 15 distribution-by-contrast primary intervals; report 99.6667% percentile intervals, a Bonferroni family coverage of approximately 95%. PMU ratios are secondary. For NYC, report each block and descriptive medians/ranges only.

## Claim boundaries

This experiment can estimate component and interaction effects for this one DuckDB query path, version, host, and build. It cannot establish portability or improvements in other systems. If heap_avx2 is as fast as or faster than array_avx2, the array is not needed to obtain the native filter benefit. If effects are inconclusive, report that. Do not infer cache causality from representation effects without cache-specific measurements.

## Artifacts

- Frozen driver: ../duckdb_topk_driver.cpp and existing driver binary; driver identity is recorded in the run manifest.
- Variant source generator: prepare_duckdb_native_factorial_variants_v1.py.
- Variant source snapshots and hashes: native-factorial-variants-v1.0/.
- Frozen run plan: this file.
- Runner/analyzer: run_duckdb_native_factorial_v1.py and analyze_duckdb_native_factorial_v1.py.
- Raw run directory: ../results/duckdb-native-factorial-v1.0/.
- Library variants are built from the same configured DuckDB build tree, copied to separately named artifact directories, and identified by SHA-256.
