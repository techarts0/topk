#!/usr/bin/env python3
"""Fixed v1.1 entrypoint for untimed path-count summary."""
import runpy, sys
from pathlib import Path
sys.argv = [str(Path(__file__).with_name("summarize_diagnostics_v1.py")),
            str(Path(__file__).parent/"results/diagnostics-v1.1-inline-avx")]
runpy.run_path(sys.argv[0],run_name="__main__")
