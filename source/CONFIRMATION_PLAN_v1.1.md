# Confirmatory C++ kernel experiment plan v1.1 (inlined AVX2)

Date: 2026-10-25 (Asia/Shanghai). This is a new confirmation for the v2 kernel after a completed v1 confirmation and an inspected v2 exploratory pilot. The v1 result was adverse for the first AVX2 implementation; disassembly showed an out-of-line helper call in every vector iteration. The v2 source moves the AVX2 comparison into a target-specific scan loop. The v2 pilot showed a favorable direction for k=100, but only three independent blocks; these observations are exploratory and are not included in confirmation. This implementation selection is disclosed and results from both versions will be preserved.

## Question and scope

For a fixed stream, does the inlined AVX2 threshold filter change full-call streaming top-k time relative to scalar threshold checks for a contiguous bounded min-heap and a sorted flat array? This tests controlled C++ kernels only. It does not establish end-to-end benefit in PostgreSQL, DuckDB, Lucene, ClickHouse, or Velox.

## Workloads and methods

Use exactly the four N=1,000,000 float64 inputs and manifests listed in `CONFIRMATION_PLAN_v1.0.md`: seeded Uniform[0,1), standard Normal, Pareto(alpha=2), and the chronological NYC TLC Jan-2024 distance stream. Test k=100 and k=10,000. Run exactly seven methods: `heap_scalar`, `heap_batch`, `heap_avx2`, `array_scalar`, `array_batch`, `array_avx2`, and `stl` (`std::partial_sort_copy`). Primary contrasts are the two structure-specific scalar/AVX2 pairs. All other comparisons are descriptive secondary results.

## Procedure and independent unit

For every dataset/k cell, collect 25 independent process blocks, each with five timed calls per method and one correctness-checked warmup. The block is the independent unit; use each process's median call time. Randomize method order within each block using the recorded per-cell seeds in `run_confirmation_v1_1.sh`; pin child processes to logical CPU 2. Do not stop early, add blocks based on observed direction, or remove outliers. Keep failed runs and document any technical rerun.

The primary time includes state initialization, full input scan, and ordered output, and excludes CSV load, reference sort, warmup, correctness comparison, checksum, and process start. Check exact output and checksum for every timed call. Environment is one WSL2 host, AMD Ryzen 9 PRO 7940HS, GCC 11.4.0/libstdc++ 11, AVX2. This does not establish CPU or compiler portability.

## Analysis

Per cell, estimate the geometric mean paired-block ratio `scalar_time / avx2_time` (above 1 favors AVX2). For the 8 primary contrasts use 100,000 paired-block bootstrap resamples with the fixed seed in `analyze_confirmation_v1_1.py` and report 99.375% percentile intervals (nominal Bonferroni-adjusted intervals; approximate simultaneous 95% coverage). An interval excluding 1 is evidence consistent with a difference for that cell. Report every cell and block spread, including null and adverse results. Do not collect more samples based on interval position. Batch/scalar, heap/array, and STL comparisons remain descriptive.

Collect separate untimed path counts and a separate gated `perf stat` matrix (cycles:u, instructions:u, branches:u, branch-misses:u; ten calls per method/cell). Report running ratios and aggregate counters only. Do not assign aggregate branch events to one source branch, infer time shares from operation counts, or claim zero stalls. Disassembly can explain this implementation's generated path but does not establish universal AVX2 behavior.

## Integrity and stopping

Freeze hashes of this plan, kernel and harness sources, binary, run/analyzer scripts, and all input manifests before timing. Stop a cell for correctness/checksum mismatch, hash mismatch, unsupported AVX2/perf, or resource exhaustion; retain evidence and report the gap. Do not alter kernel, input, or analysis after timing starts. All results go under a new v1.1 directory, separate from v1 and the pilot.
