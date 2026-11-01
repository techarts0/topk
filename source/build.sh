#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
flags=(-std=c++20 -O3 -g -Wall -Wextra -Wpedantic -fno-omit-frame-pointer)
# AVX2 is confined to target-attributed functions; no global -march=native.
"${CXX:-g++}" "${flags[@]}" bench.cpp -o build/topk_bench
printf '%s\n' "${CXX:-g++} ${flags[*]} bench.cpp -o build/topk_bench" > build/command.txt
"${CXX:-g++}" --version > build/compiler.txt
build/topk_bench --version > build/version.txt
sha256sum bench.cpp kernels.hpp build/topk_bench > build/hashes.txt
stdlib_header="/usr/include/c++/$(${CXX:-g++} -dumpversion)/bits/stl_algo.h"
if [[ -f "$stdlib_header" ]]; then sha256sum "$stdlib_header" >> build/hashes.txt; fi
if [[ "${1:-}" == "sanitize" ]]; then
  "${CXX:-g++}" -std=c++20 -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer bench.cpp -o build/topk_sanitize
  build/topk_sanitize --self-test
fi
