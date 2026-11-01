#!/usr/bin/env python3
"""Fixed v1.1 entrypoint for the validated v1.0 analysis implementation."""
import runpy, sys
from pathlib import Path
root = Path(__file__).parent / "results/confirm-v1.1-inline-avx"
sys.argv = [str(Path(__file__).with_name("analyze_confirmation.py")), str(root)]
runpy.run_path(sys.argv[0], run_name="__main__")
