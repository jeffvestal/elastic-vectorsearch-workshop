#!/usr/bin/env python3
"""Copy the read-only workshop sources into $HARNESS/work (explicit file list only)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

common.stage_sources(force=True)
print(f"staged sources into {common.WORK}")
