# Exact Top-k Selection: Supplementary Materials

This repository contains the code, frozen inputs, experimental records, analysis outputs, and run metadata supporting *Engineering Exact Top-k Selection: System Audits and Optimization in DuckDB*. 


## Contents

- `source/bench.cpp`, `source/kernels.hpp`, and `source/integration/` contain the controlled kernels, DuckDB drivers and source variants, frozen experiment plans, analysis scripts, and build/run scripts.
- `source/data/submission_inputs_part01.zip` through `submission_inputs_part03.zip` contain the 30 synthetic streams and one chronological NYC taxi stream used in the reported experiments. Each input has a JSON provenance sidecar with a SHA-256 digest.
- `source/results/` contains process-level timing records, PMU results, run manifests, plans, checksums, and stdout/stderr logs for the completed experiments reported or discussed in the manuscript.
- `source/integration/filter-attribution-v1.0/build-artifacts/` contains compiler vectorization reports and object-level disassemblies used to inspect code generation. The 637 MiB whole-library disassembly and large DuckDB build caches are omitted. A small archived controlled-kernel executable is retained only to document the earlier helper-call regression.
- `provenance/` contains redacted archival run-script copies, selected controlled-kernel build metadata, and the archived v1 executable/disassembly relevant to the earlier helper-call regression. Use the portable runners under `source/` to reproduce the experiments.
- `licenses/DuckDB-MIT.txt` contains the license for DuckDB-derived source variants included here.
- `SHA256SUMS.txt` lists checksums for every package file except itself.

The legacy `topk/Supplementary Material` directory belongs to the earlier manuscript and has not been changed.

## Inputs and logs

The CSV inputs total about 520 MiB before compression. They are divided into three ZIP archives, each below 100 MB, because GitHub blocks individual regular Git files above that limit. Each archive is above GitHub's 50 MiB warning threshold, so add them with Git rather than the browser uploader. For a smaller Git history, publish the archives as release assets or use Git LFS. See [GitHub's large-file guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github). The NYC taxi source Parquet file is not bundled. Its sidecar records the source URL and hash, and the included preparation script documents the extraction.

The archives can be extracted and verified from this directory with:

```bash
python3 extract_input_data.py
```

The raw per-process records are included so readers can trace summary tables to the underlying observations and inspect plans, counters, and run metadata. The package contains the completed DuckDB factorial, the separate profiler run, the three-build attribution run, the controlled C++ timing and PMU runs, and the earlier AVX2 helper confirmation discussed in the manuscript. Development smoke tests and unrelated pilot matrices are excluded.

The JSON sidecars in the input archives use portable relative paths. Historical run manifests, raw logs, and archival script copies replace machine-specific absolute path roots with `*`; relative package structure is retained where possible.

## Reproduction

The recorded experiments ran on an AMD Ryzen 9 PRO 7940HS with Ubuntu 22.04, Linux kernel `6.6.87.2-microsoft-standard-WSL2`, GCC 11.4.0, and DuckDB 1.4.0. These are the recorded conditions; no bare-metal or native-Linux claim is made. Run manifests preserve the recorded environment, with the local host name redacted.

After extracting the inputs, the controlled C++ sources build with `bash source/build.sh`. The timing runner and analysis script are `source/integration/run_factorial_v1_1.py` and `source/integration/analyze_factorial_v1_1.py`; the controlled PMU runner is `source/run_perf_blocks_v1_1.py`. Their frozen plans are stored next to the scripts. NumPy is required for bootstrap analysis.

The DuckDB variants are derived from upstream tag `v1.4.0`, commit `b8a06e4a22672e254cd0baa68a3dbed2eb51c56e`. The upstream DuckDB source tree is not bundled. To rebuild the variants, check out that commit under `source/integration/duckdb-v1.4.0`, configure a Release build with `BUILD_SHELL=OFF`, `BUILD_UNITTESTS=OFF`, and `ENABLE_EXTENSION_AUTOLOADING=OFF`, then follow the included DuckDB build and run scripts. The compiled libraries and build tree are omitted; recorded hashes and build configuration are in the result manifests and `provenance/duckdb_build_configuration.txt`. Runner copies in this package resolve paths relative to their location. Redacted archival runner copies are under `provenance/original_run_scripts/`; use the portable scripts under `source/` for reproduction.

Run scripts refuse to overwrite existing result directories. Use a fresh copy of the package for a new run. Timing results are not expected to match across hosts.

## Manuscript result map

| Manuscript result | Artifact directory / file |
|---|---|
| Four-project source audit | Manuscript Table 1 and its version-pinned source references |
| DuckDB four-cell query factorial | `source/results/duckdb-native-factorial-v1.0/` |
| Scalar-specialization vs. AVX2 attribution | `source/results/duckdb-filter-attribution-v1.0/` |
| DuckDB PMU counters (two separately labeled runs) | The preceding two result directories |
| DuckDB operator timing and root latency | `source/results/duckdb-native-operator-profile-v1.0/` |
| Controlled replacement counts and C++ kernel timing | `source/results/factorial-v1.1/` |
| Controlled C++ PMU counters | `source/results/perf-blocks-v1.1-inline-avx/` |
| Earlier helper-based AVX2 regression discussed in Methods | `source/results/confirm-v1/` and `provenance/controlled_build/archive/v1/` |

The four system audits are source-path inspections within the scope described in the paper; they are not four cross-system performance benchmarks.
