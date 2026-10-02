"""Shared helpers for the ES|QL workshop test harness.

Credentials are read ONLY from the environment: ES_ENDPOINT, ES_API_KEY, ES_KIBANA_URL.
Nothing in here prints or logs the API key.
"""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

HARNESS = Path(__file__).resolve().parent.parent
OUT = HARNESS / "out"
WORK = HARNESS / "work"

# Read-only sources (override with env vars if they move).
WORKSHOP_DIR = Path(os.environ.get("WORKSHOP_DIR", str(HARNESS.parent)))
# The Instruqt assignment.md files live in elastic/instruqt-field-tracks-dev.
ASSIGNMENT_DIR = Path(os.environ.get(
    "ASSIGNMENT_DIR",
    str(Path.home() / "repos/instruqt-field-tracks-dev/tracks/vector-keyword-hybrid-retrieval")))

INDEX = "aiewf-workshop-docs"
TOOL_ID = "search-workshop-docs-hybrid"
AGENT_ID = "workshop-docs-agent"

LAB_DIRS = ["01-esql-vector-search", "02-esql-where-vector-breaks", "03-esql-hybrid-search",
            "04-esql-rag-pipeline", "05-esql-reranking"]
NOTEBOOKS = ["lab1-esql-semantic-search.ipynb", "lab2-esql-where-vector-breaks.ipynb",
             "lab3-esql-hybrid-search.ipynb", "lab4-esql-rag-pipeline.ipynb",
             "lab5-esql-reranking.ipynb"]

# The lab 4 two-part question exactly as lab4-esql-rag-pipeline.ipynb cell 13 asks it.
LAB4_AGENT_QUESTION = (
    "My Elasticsearch container keeps dying with exit code 137. Why does that happen, "
    "and what specific JVM and memory settings should I change to prevent it?"
)
LAB4_RAG_QUESTION = "How does Index Lifecycle Management move data through hot, warm, and cold phases?"

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(s: str) -> str:
    return ANSI.sub("", s or "")


def require_env(names=("ES_ENDPOINT", "ES_API_KEY", "ES_KIBANA_URL"), optional=()):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        print(f"ERROR: missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        print("       Export ES_ENDPOINT, ES_API_KEY, ES_KIBANA_URL (values are never printed).", file=sys.stderr)
        sys.exit(2)
    if os.environ.get("ES_ENDPOINT"):
        os.environ["ES_ENDPOINT"] = os.environ["ES_ENDPOINT"].rstrip("/")
    if os.environ.get("ES_KIBANA_URL"):
        os.environ["ES_KIBANA_URL"] = os.environ["ES_KIBANA_URL"].rstrip("/")
    # Lab 4 notebook + setup_agent.py read KIBANA_URL.
    if os.environ.get("ES_KIBANA_URL"):
        os.environ["KIBANA_URL"] = os.environ["ES_KIBANA_URL"]


def host_of(url: str) -> str:
    return urlparse(url).hostname or ""


def stage_sources(force=False):
    """Copy ONLY explicitly-named source files into $HARNESS/work (never globs dotfiles / .env)."""
    marker = WORK / ".staged"
    if marker.exists() and not force:
        return
    (WORK / "corpus").mkdir(parents=True, exist_ok=True)
    (WORK / "agent-builder").mkdir(parents=True, exist_ok=True)
    (WORK / "notebooks-esql").mkdir(parents=True, exist_ok=True)
    (WORK / "docs-esql").mkdir(parents=True, exist_ok=True)
    (WORK / "assignments").mkdir(parents=True, exist_ok=True)
    for f in ("ingest.py", "docs.json"):
        shutil.copy2(WORKSHOP_DIR / "corpus" / f, WORK / "corpus" / f)
    shutil.copy2(WORKSHOP_DIR / "agent-builder" / "setup_agent.py", WORK / "agent-builder" / "setup_agent.py")
    for nb in NOTEBOOKS:
        shutil.copy2(WORKSHOP_DIR / "notebooks-esql" / nb, WORK / "notebooks-esql" / nb)
    for md in ("TRAP_QUERY_VALIDATION_ESQL.md", "HANDOFF-ESQL.md", "README-ESQL.md"):
        shutil.copy2(WORKSHOP_DIR / "docs-esql" / md, WORK / "docs-esql" / md)
    for d in LAB_DIRS:
        (WORK / "assignments" / d).mkdir(parents=True, exist_ok=True)
        shutil.copy2(ASSIGNMENT_DIR / d / "assignment.md", WORK / "assignments" / d / "assignment.md")
    shutil.copy2(ASSIGNMENT_DIR / "01-esql-vector-search" / "setup-kubernetes-vm",
                 WORK / "assignments" / "01-esql-vector-search" / "setup-kubernetes-vm")
    marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))


def find_line(path: Path, snippet: str) -> int:
    """1-based line number of the first line containing snippet (0 if not found)."""
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if snippet in line:
                return i
    except OSError:
        pass
    return 0


# ---------------------------------------------------------------------------
# ES|QL over HTTP
# ---------------------------------------------------------------------------
class Result:
    def __init__(self, status, columns=None, values=None, error="", elapsed=0.0, raw=None):
        self.status = status
        self.columns = columns or []
        self.values = values or []
        self.error = error
        self.elapsed = elapsed
        self.raw = raw

    @property
    def ok(self):
        return self.status == 200

    @property
    def names(self):
        return [c["name"] for c in self.columns]

    @property
    def rows(self):
        n = self.names
        return [dict(zip(n, v)) for v in self.values]

    @property
    def ids(self):
        return [r.get("id") for r in self.rows]

    def scores(self):
        return [r.get("_score") for r in self.rows]

    def rank(self, doc_id):
        ids = self.ids
        return ids.index(doc_id) + 1 if doc_id in ids else None

    def top(self, n=5):
        out = []
        for r in self.rows[:n]:
            s = r.get("_score")
            out.append(f"{r.get('id')}" + (f"({s:.4f})" if isinstance(s, (int, float)) else ""))
        return ", ".join(out) if out else "(no rows)"


def _headers():
    return {"Authorization": f"ApiKey {os.environ['ES_API_KEY']}", "Content-Type": "application/json"}


_CACHE = {}


def esql(query, params=None, timeout=240, retries=2, cache=True):
    """POST {ES_ENDPOINT}/_query?format=json. params = list of {"name": value}."""
    import requests
    key = (query, json.dumps(params, sort_keys=True) if params else "")
    if cache and key in _CACHE:
        return _CACHE[key]
    body = {"query": query}
    if params:
        body["params"] = params
    url = f"{os.environ['ES_ENDPOINT']}/_query?format=json"
    res = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            r = requests.post(url, headers=_headers(), json=body, timeout=timeout)
        except requests.RequestException as e:
            res = Result(0, error=f"{type(e).__name__}: {str(e)[:200]}", elapsed=time.time() - t0)
        else:
            el = time.time() - t0
            try:
                js = r.json()
            except ValueError:
                js = None
            if r.status_code == 200 and isinstance(js, dict):
                res = Result(200, js.get("columns"), js.get("values"), "", el, js)
            else:
                err = ""
                if isinstance(js, dict):
                    e = js.get("error")
                    if isinstance(e, dict):
                        err = e.get("reason") or json.dumps(e)[:300]
                        rc = e.get("root_cause")
                        if rc and isinstance(rc, list) and rc and rc[0].get("reason"):
                            err = rc[0]["reason"]
                    else:
                        err = str(e or js)[:300]
                else:
                    err = (r.text or "")[:300]
                res = Result(r.status_code, error=err.replace("\n", " ")[:400], elapsed=el, raw=js)
        if res.status in (0, 429, 502, 503, 504) and attempt < retries:
            time.sleep(3 * (attempt + 1))
            continue
        break
    res.query = query
    res.params = params
    if cache:
        _CACHE[key] = res
    return res


def lit(s: str) -> str:
    """ES|QL string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def es_get(path, timeout=60):
    import requests
    return requests.get(f"{os.environ['ES_ENDPOINT']}{path}", headers=_headers(), timeout=timeout)


def kibana_headers(internal_origin=False):
    h = {"Authorization": f"ApiKey {os.environ['ES_API_KEY']}", "kbn-xsrf": "true",
         "Content-Type": "application/json"}
    if internal_origin:
        h["x-elastic-internal-origin"] = "Kibana"
    return h
