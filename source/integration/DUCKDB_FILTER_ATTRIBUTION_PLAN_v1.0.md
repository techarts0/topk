# DuckDB native filtering attribution experiment v1.0

Frozen: 2026-10-26 (Asia/Shanghai), before any supplemental outcome collection. Existing v1.0 factorial outcomes have been inspected and are not reused as observations here. This experiment collects new process-level measurements on the same frozen datasets and query.

## Question and estimands

For DuckDB v1.4.0, one thread, `SELECT score FROM topk_input ORDER BY score DESC LIMIT 100`, quantify (a) the effect of a type/query-specialized scalar boundary filter relative to DuckDB's original generic filter, and (b) the additional effect of the explicit AVX2 filter relative to that otherwise equivalent specialized scalar filter. The heap remains DuckDB's original heap in all cells. This experiment does not estimate a universal AVX2 effect or effects at other k values.

For each of Uniform, Normal, and Pareto(alpha=2), the estimand is the equally seed-weighted geometric-mean ratio of query-plus-complete-result-consumption times. Ratios are reference time / treatment time; above one favors the named treatment. Comparisons are original/scalar-specialized, scalar-specialized/AVX2-specialized, and original/AVX2-specialized. The first two answer the attribution questions; the third is a consistency contrast. NYC is descriptive only.

## Factor cells

All builds share DuckDB v1.4.0 commit, release build settings, driver, guard cases, query plan, and original heap.

- `heap_stock`: original DuckDB boundary filter.
- `heap_scalar_specialized`: same runtime/type/order/validity/offset guards as AVX2, same fixed boundary per filter call, same conservative NaN candidate handling, and direct writes to the same final selection vector, but ordinary C++ scalar comparisons and no explicit intrinsics.
- `heap_avx2`: existing runtime-guarded AVX2 specialization.

The scalar C++ implementation may be auto-vectorized by GCC at `-O3`; this is observed from vectorizer diagnostics and the generated object code, not assumed away. Do not use `-fno-tree-vectorize`. The AVX2 and scalar paths retain the same eligibility condition including the existing k<=100 small-heap boundary.

## Workloads, correctness, and protocol

Use the same frozen 31 input files as native factorial v1.0: ten seeds per each of three synthetic populations and one chronological NYC stream. All observations from the earlier experiment have been inspected; supplemental timing data are newly collected and reported separately. Before timing, run the existing DuckDB edge suite against all three libraries. Require identical edge hashes, identical TOP_N plan, correct full-sort outputs, and paired-block output checksums.

For each stream, collect ten independent fresh-process three-way paired blocks. Randomize cell order with Python `random.Random(7319042)`; pin each process to logical CPU 2. Each fresh process builds an in-memory table, checks one full-sort warm-up, and records three timed query-plus-full-fetch calls. This is 310 paired blocks, 930 variant processes, and 2,790 timed calls. Preserve every success, failure, timeout, process order, raw output, plan, build hash, and environment record. No silent reruns or outcome-based exclusions. If a process/build/correctness/plan gate fails, stop and preserve the partial run with the reason.

Collect cycles, instructions, branches, and branch misses with the existing grouped perf_event_open protocol. PMU results are secondary; only report event contrasts where running percentage is at least 95%. Timing is the primary outcome.

## Inference and decision criteria

Within each process, use the median of three calls. Within each seed and contrast, average paired log ratios across the ten process blocks. Estimate the geometric mean with equal weight per seed. Use a nested paired bootstrap (resample seeds, then paired blocks within sampled seed) with 100,000 replicates. The family contains all 9 distribution-by-contrast intervals; use 99.4444% percentile intervals (Bonferroni familywise coverage approximately 95%). Report all per-distribution estimates and intervals. Do not infer equivalence from a non-significant difference. No practical equivalence margin has been prespecified, so use inconclusive language whenever the interval includes one. NYC: report ten paired block ratios, median and range only.

Machine-code audit: preserve Release compile flags and source/object/library hashes. Save GCC vectorization diagnostics for the scalar-specialized source and disassembly of the compiled scalar and AVX2 objects. Determine whether the relevant filtering loop was auto-vectorized and identify vector comparison/mask instructions in the optimized code. Do not infer a causal instruction-level explanation solely from aggregate PMU counts.

## Scope and stopping

This is a single-host, single-query, single-k mechanism experiment. It estimates implementation effects on the tested build and workloads; it does not establish portability. No outcome-dependent sample-size extensions are allowed. If desired precision is inadequate at the planned 10 blocks per stream, report uncertainty and design a new versioned plan rather than extending this run after inspecting significance.

## Provenance

- Existing baseline library and AVX2 source/library are identified by SHA-256 in the run manifest.
- New scalar source is deterministically derived from the existing heap+AVX2 source and stored beside this plan.
- Results are written to `source/results/duckdb-filter-attribution-v1.0/`; this directory must not pre-exist.
- Analysis script, raw logs, vectorization diagnostics, disassembly, and result manifest remain with the new run.
