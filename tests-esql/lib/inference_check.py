#!/usr/bin/env python3
"""Dump GET _inference/_all (inference_id + task_type ONLY) and assert every inference id
referenced by the notebooks / assignments exists (ids are extracted by regex, not hard-coded)."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

common.require_env()
common.stage_sources()

# A dotted-prefix inference id: ".name-with-hyphen..." not preceded by a word char or slash/dot.
ID_RE = re.compile(r"(?<![\w/.])(\.[a-z][a-z0-9]*(?:-[a-z0-9][a-z0-9._]*)+)")

sources = list((common.WORK / "notebooks-esql").glob("*.ipynb"))
sources += list((common.WORK / "assignments").glob("*/assignment.md"))
sources += [common.WORK / "agent-builder" / "setup_agent.py"]

found = {}
for p in sources:
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".ipynb":
        nb = json.loads(text)
        text = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
    for m in ID_RE.finditer(text):
        iid = m.group(1).rstrip(".-")
        found.setdefault(iid, set()).add(p.name if p.name != "assignment.md" else p.parent.name)

r = common.es_get("/_inference/_all")
print(f"GET _inference/_all -> HTTP {r.status_code}")
if r.status_code != 200:
    print("ERROR body (truncated):", r.text[:300])
    sys.exit(3)
eps = r.json().get("endpoints", [])
slim = [{"inference_id": e.get("inference_id"), "task_type": e.get("task_type")} for e in eps]
(common.OUT).mkdir(parents=True, exist_ok=True)
(common.OUT / "inference_endpoints.json").write_text(json.dumps(slim, indent=2))
by_id = {e["inference_id"]: e["task_type"] for e in slim}
print(f"{len(slim)} endpoints on cluster (inference_id + task_type saved to out/inference_endpoints.json)")

print("\nReferenced inference ids (extracted by regex from notebooks/assignments/setup_agent.py):")
fails = 0
EXPECT_TASK = {"embedding": "text_embedding", "reranker": "rerank", "completion": "completion"}
for iid in sorted(found):
    present = iid in by_id
    tt = by_id.get(iid, "-")
    note = ""
    for k, want in EXPECT_TASK.items():
        if k in iid and present and tt != want and not iid.endswith("chat_completion"):
            note = f"  <-- task_type {tt!r}, expected {want!r}"
            fails += 1
    mark = "OK     " if present else "MISSING"
    if not present:
        fails += 1
    print(f"  [{mark}] {iid:<48} task_type={tt:<16} used in: {', '.join(sorted(found[iid]))}{note}")
if not found:
    print("  (none extracted -- regex problem?)")
    fails += 1
print(f"\ninference check: {'PASS' if not fails else 'FAIL'} ({fails} problem(s))")
sys.exit(1 if fails else 0)
