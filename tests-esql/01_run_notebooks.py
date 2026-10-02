#!/usr/bin/env python3
"""Execute the 5 ES|QL lab notebooks with nbclient against the cluster in the env vars.

* kernel = the harness venv's python (kernel 'python3' resolved by jupyter_client -> sys.executable)
* per-cell timeout 300s, allow_errors=True (every cell runs even if an earlier one errored)
* env vars pass through to the kernel; KIBANA_URL is derived from ES_KIBANA_URL (Lab 4 needs it)
* executed copies  -> out/executed/<nb>.ipynb
* text outputs     -> out/executed/<nb>.txt   (+ any image/png outputs -> out/executed/images/)
* summary          -> stdout and out/notebooks_summary.json

Usage:  01_run_notebooks.py [--only lab3 lab4] [--timeout 300] [--src DIR] [--out DIR]
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import common  # noqa: E402

import nbformat  # noqa: E402
from nbclient import NotebookClient  # noqa: E402
from nbclient.exceptions import CellTimeoutError, DeadKernelError  # noqa: E402


def cell_text_outputs(cell):
    """Return a list of text chunks for a code cell's outputs."""
    chunks = []
    for o in cell.get("outputs", []):
        t = o.get("output_type")
        if t == "stream":
            chunks.append(f"[{o.get('name', 'stream')}]\n{o.get('text', '')}")
        elif t in ("execute_result", "display_data"):
            data = o.get("data", {})
            if "text/plain" in data:
                chunks.append(f"[{t}]\n{data['text/plain']}")
            elif data:
                chunks.append(f"[{t}: {', '.join(data.keys())}]")
        elif t == "error":
            tb = common.strip_ansi("\n".join(o.get("traceback", [])))
            chunks.append(f"[ERROR {o.get('ename')}: {common.strip_ansi(o.get('evalue', ''))}]\n{tb}")
    return chunks


def first_lines_of_error(cell, n=3):
    """First n non-blank traceback lines (ANSI stripped) + a final 'ename: evalue' line."""
    for o in cell.get("outputs", []):
        if o.get("output_type") == "error":
            tb = common.strip_ansi(chr(10).join(o.get("traceback", []))).strip().splitlines()
            tb = [l for l in tb if l.strip()][:n]
            tb.append(f"=> {o.get('ename')}: {common.strip_ansi(str(o.get('evalue')))[:300]}")
            return tb
    return []


def run_one(path: Path, out_dir: Path, timeout: int):
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(
        nb, timeout=timeout, kernel_name="python3", allow_errors=True,
        interrupt_on_timeout=True, resources={"metadata": {"path": str(out_dir)}},
    )
    n_code = sum(1 for c in nb.cells if c.cell_type == "code")
    timings = {}
    timeouts = []
    t_start = time.time()
    dead = False
    try:
        with client.setup_kernel():
            for idx, cell in enumerate(nb.cells):
                if cell.cell_type != "code":
                    continue
                t0 = time.time()
                try:
                    client.execute_cell(cell, idx)
                except CellTimeoutError as e:
                    timeouts.append(idx)
                    cell.setdefault("outputs", []).append(nbformat.v4.new_output(
                        "error", ename="CellTimeoutError", evalue=f"cell exceeded {timeout}s", traceback=[str(e)]))
                except DeadKernelError as e:
                    cell.setdefault("outputs", []).append(nbformat.v4.new_output(
                        "error", ename="DeadKernelError", evalue=str(e), traceback=[str(e)]))
                    dead = True
                    break
                except Exception as e:  # noqa: BLE001  (keep going: harness must not die mid-notebook)
                    cell.setdefault("outputs", []).append(nbformat.v4.new_output(
                        "error", ename=type(e).__name__, evalue=str(e)[:500], traceback=[str(e)[:500]]))
                timings[idx] = time.time() - t0
    except Exception as e:  # noqa: BLE001
        return {"notebook": path.name, "fatal": f"{type(e).__name__}: {e}", "cells_run": 0,
                "code_cells": n_code, "errors": [], "elapsed": time.time() - t_start}

    exec_path = out_dir / path.name
    nbformat.write(nb, exec_path)

    # text dump + image extraction
    img_dir = out_dir / "images"
    img_dir.mkdir(exist_ok=True)
    lines = [f"# {path.name} -- executed {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    errors = []
    ran = 0
    img_n = 0
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        if cell.get("execution_count") is not None or cell.get("outputs"):
            ran += 1
        src_head = "\n".join(cell.source.splitlines()[:3])
        lines.append("=" * 78)
        lines.append(f"CELL {idx}  ({timings.get(idx, 0):.1f}s)")
        lines.append("-- source (first lines) --")
        lines.append(src_head)
        lines.append("-- output --")
        lines.extend(cell_text_outputs(cell) or ["(no output)"])
        for o in cell.get("outputs", []):
            if o.get("output_type") in ("display_data", "execute_result") and "image/png" in o.get("data", {}):
                img_n += 1
                fn = img_dir / f"{path.stem}-cell{idx}-{img_n}.png"
                fn.write_bytes(base64.b64decode(o["data"]["image/png"]))
                lines.append(f"[image saved: {fn.relative_to(out_dir.parent)}]")
        err = first_lines_of_error(cell)
        if err:
            if "KeyboardInterrupt" in err[-1] and timings.get(idx, 0) >= timeout - 2:
                err.append(f"=> (cell hit the {timeout}s per-cell timeout and was interrupted)")
                timeouts.append(idx)
            errors.append({"cell": idx, "traceback_head": err})
    (out_dir / (path.stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")
    return {"notebook": path.name, "cells_run": ran, "code_cells": n_code, "errors": errors,
            "timeouts": timeouts, "dead_kernel": dead, "elapsed": round(time.time() - t_start, 1),
            "executed_copy": str(exec_path), "text_dump": str(out_dir / (path.stem + ".txt"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="substrings of notebook names, e.g. lab3 lab4")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--src", default=None, help="notebook dir (default: staged notebooks-esql)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-env-check", action="store_true", help="(self-test with dummy notebooks only)")
    a = ap.parse_args()

    if not a.no_env_check:
        common.require_env()
    common.stage_sources()
    src = Path(a.src) if a.src else common.WORK / "notebooks-esql"
    out_dir = Path(a.out) if a.out else common.OUT / "executed"
    out_dir.mkdir(parents=True, exist_ok=True)

    nbs = sorted(src.glob("*.ipynb"))
    if a.only:
        nbs = [p for p in nbs if any(s in p.name for s in a.only)]
    if not nbs:
        print("no notebooks found in", src)
        return 2

    print(f"Running {len(nbs)} notebook(s) from {src}\n  executed copies -> {out_dir}\n")
    summaries = []
    for p in nbs:
        print(f"--- {p.name}: executing (per-cell timeout {a.timeout}s) ...", flush=True)
        s = run_one(p, out_dir, a.timeout)
        summaries.append(s)
        if s.get("fatal"):
            print(f"    FATAL: {s['fatal']}")
            continue
        print(f"    cells run: {s['cells_run']}/{s['code_cells']}   cells errored: {len(s['errors'])}"
              f"   elapsed: {s['elapsed']}s" + ("   [DEAD KERNEL]" if s.get("dead_kernel") else ""))
        for e in s["errors"]:
            print(f"    ERROR cell {e['cell']}:")
            for l in e["traceback_head"]:
                print(f"        {l[:200]}")
        print(f"    text outputs: {s['text_dump']}")

    (common.OUT / "notebooks_summary.json").write_text(json.dumps(summaries, indent=2))
    total_err = sum(len(s["errors"]) for s in summaries) + sum(1 for s in summaries if s.get("fatal"))
    print("\n==== SUMMARY ====")
    print(f"{'notebook':<40} {'run':>7} {'errors':>7}")
    for s in summaries:
        print(f"{s['notebook']:<40} {s.get('cells_run', 0):>3}/{s.get('code_cells', 0):<3} {len(s['errors']):>7}")
    print(f"total errored cells: {total_err}")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
