#!/usr/bin/env python3
"""Agent Builder checks via the Kibana API (mirrors setup_agent.py / lab4 notebook cell 13).

1. GET tool `search-workshop-docs-hybrid`, agent `workshop-docs-agent` (and skill) -> print definitions
2. POST /api/agent_builder/tools/_execute smoke test (what setup_agent.py step 4 does)
3. POST /api/agent_builder/converse {"agent_id":..., "input": <lab 4 two-part question>}  (notebook cell 13)
   -> count tool calls / retrieval hops, print reasoning + final answer
Headers: Authorization: ApiKey, kbn-xsrf: true; if a call fails it is retried once with
x-elastic-internal-origin: Kibana. Raw JSON saved to out/agent/. Env: ES_API_KEY, ES_KIBANA_URL only.
"""
import argparse
import ast
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import common  # noqa: E402
import requests  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--probe", type=int, default=0, help="N fresh converse runs per question (hop-count probe)")
ap.add_argument("--alt", action="store_true", help="also probe the harness-derived alternative two-part questions")
ap.add_argument("--connector-id", default=None, help="pass connector_id in the converse body (pinning test; unverified field)")
args = ap.parse_args()
common.require_env(("ES_API_KEY", "ES_KIBANA_URL"))
common.stage_sources()
KB = os.environ["ES_KIBANA_URL"]
OUTD = common.OUT / "agent"
OUTD.mkdir(parents=True, exist_ok=True)
TOOL, AGENT, SKILL = common.TOOL_ID, common.AGENT_ID, "workshop-docs-diagnose-fix"


def question_from_notebook():
    nb = json.load(open(common.WORK / "notebooks-esql" / "lab4-esql-rag-pipeline.ipynb"))
    for c in nb["cells"]:
        src = "".join(c["source"])
        if c["cell_type"] == "code" and "agent_question" in src:
            try:
                for node in ast.walk(ast.parse(src)):
                    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "agent_question" for t in node.targets):
                        return ast.literal_eval(node.value)
            except Exception:  # noqa: BLE001
                pass
    return common.LAB4_AGENT_QUESTION


def kb(method, path, body=None, timeout=60):
    """Call Kibana; if non-2xx retry once with x-elastic-internal-origin. Returns (status, json|text, note)."""
    notes = []
    last = None
    for internal in (False, True):
        try:
            r = requests.request(method, f"{KB}{path}", headers=common.kibana_headers(internal), json=body, timeout=timeout)
        except requests.RequestException as e:
            last = (0, f"{type(e).__name__}: {e}", f"internal_origin={internal}")
            notes.append(f"{'internal-origin' if internal else 'plain'}: {type(e).__name__}")
            continue
        try:
            payload = r.json()
        except ValueError:
            payload = r.text[:500]
        last = (r.status_code, payload, "internal-origin header used" if internal else "plain headers")
        if 200 <= r.status_code < 300:
            return last
        notes.append(f"{'internal-origin' if internal else 'plain'}: HTTP {r.status_code}")
        if r.status_code in (429,) or r.status_code >= 500:
            break
    return last[0], last[1], "; ".join(notes)


def save(name, obj):
    (OUTD / name).write_text(json.dumps(obj, indent=2, default=str) if not isinstance(obj, str) else obj)


checks = []


def check(name, ok, detail=""):
    checks.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")


# ---------------------------------------------------------------- definitions
print("== GET tool / agent / skill definitions ==")
st, tool, note = kb("GET", f"/api/agent_builder/tools/{TOOL}")
print(f"\n--- tool {TOOL}: HTTP {st} ({note})")
print(json.dumps(tool, indent=2)[:6000])
save("tool.json", {"http": st, "body": tool})
check(f"tool {TOOL} exists", st == 200, f"HTTP {st}")
if st == 200 and isinstance(tool, dict):
    check("tool type is esql", tool.get("type") == "esql", f"type={tool.get('type')}")
    q = (tool.get("configuration") or {}).get("query", "")
    check("tool ES|QL is FORK|FUSE hybrid over aiewf-workshop-docs", "FORK" in q.upper() and "FUSE" in q.upper() and common.INDEX in q, "")

st, agent, note = kb("GET", f"/api/agent_builder/agents/{AGENT}")
print(f"\n--- agent {AGENT}: HTTP {st} ({note})")
print(json.dumps(agent, indent=2)[:8000])
save("agent.json", {"http": st, "body": agent})
check(f"agent {AGENT} exists", st == 200, f"HTTP {st}")
if st == 200 and isinstance(agent, dict):
    cfg = agent.get("configuration") or {}
    tids = [t for g in cfg.get("tools", []) for t in g.get("tool_ids", [])]
    check("agent is wired to the hybrid tool", TOOL in tids, f"tool_ids={tids}")
    check("agent name is 'Workshop Docs Agent' (lab 4 tells learners to look for it)", agent.get("name") == "Workshop Docs Agent", f"name={agent.get('name')!r}")
    check("agent instructions describe a SECOND search (multi-hop)", "SECOND" in (cfg.get("instructions") or ""), "")
    print(f"  skill_ids on agent: {cfg.get('skill_ids')}")

st, skill, note = kb("GET", f"/api/agent_builder/skills/{SKILL}")
print(f"\n--- skill {SKILL}: HTTP {st} ({note})")
print(json.dumps(skill, indent=2)[:2500])
save("skill.json", {"http": st, "body": skill})
print(f"  (skill is optional per setup_agent.py; HTTP {st})")

# ---------------------------------------------------------------- tool smoke test
print("\n== tool _execute smoke test (setup_agent.py step 4) ==")
st, ex, note = kb("POST", "/api/agent_builder/tools/_execute", {"tool_id": TOOL, "tool_params": {"query": "notify me when something goes wrong"}})
save("tool_execute.json", {"http": st, "body": ex})
txt = json.dumps(ex)
check("tool _execute returns results", st == 200, f"HTTP {st} ({note})")
pos = txt.find("doc-049")
check("tool _execute: 'notify me when something goes wrong' surfaces doc-049 (DERIVED from setup_agent.py comment)", pos >= 0,
      f"doc-049 found at char {pos} of {len(txt)}; (first-occurrence only - rank not parsed)")

# ---------------------------------------------------------------- converse
Q = question_from_notebook()
print(f"\n== converse: lab 4 two-part question ==\n{Q}\n(running the agent loop server-side; notebook says ~15-25s)")
t0 = time.time()
st, res, note = kb("POST", "/api/agent_builder/converse", {"agent_id": AGENT, "input": Q}, timeout=420)
el = time.time() - t0
save("converse_raw.json", {"http": st, "elapsed_s": round(el, 1), "request_input": Q, "body": res})
print(f"HTTP {st} in {el:.1f}s ({note})")
check("converse HTTP 200", st == 200, f"HTTP {st}")
summary = {"http": st, "elapsed_s": round(el, 1)}
if st == 200 and isinstance(res, dict):
    steps = res.get("steps", []) or []
    calls = [s for s in steps if s.get("type") == "tool_call"]
    hops = [s for s in calls if isinstance(s.get("params"), dict) and "query" in (s.get("params") or {})]
    skills = [s for s in calls if isinstance(s.get("params"), dict) and "skill" in (s.get("params") or {})]
    print(f"\nstep types: {sorted({s.get('type') for s in steps})}   total steps: {len(steps)}")
    for s in steps:
        t = s.get("type")
        if t == "reasoning":
            print(f"  [reasoning] {str(s.get('reasoning'))[:300]}")
        elif t == "tool_call":
            print(f"  [tool_call] {s.get('tool_id')}  params={json.dumps(s.get('params'))[:300]}")
        else:
            print(f"  [{t}] {json.dumps(s)[:200]}")
    resp = res.get("response", "")
    answer = resp if isinstance(resp, str) else (resp.get("message") if isinstance(resp, dict)
             else "".join(b.get("text", "") for b in resp if isinstance(b, dict)))
    answer = answer or ""
    usage = res.get("model_usage", {})
    print(f"\nTOOL CALLS: {len(calls)} total ({len(hops)} retrieval hops with a `query` param, {len(skills)} skill loads)   LLM calls: {usage.get('llm_calls', '?')}")
    print("\n=== FINAL ANSWER ===\n" + answer + "\n====================")
    (OUTD / "converse_answer.txt").write_text(answer)
    summary.update({"tool_calls": len(calls), "retrieval_hops": len(hops), "skill_loads": len(skills),
                    "hop_queries": [h["params"]["query"] for h in hops], "tools_called": [c.get("tool_id") for c in calls],
                    "llm_calls": usage.get("llm_calls"), "answer_chars": len(answer), "model_usage": usage})
    ln = common.find_line(common.WORK / "docs-esql" / "README-ESQL.md", "converse shows")
    check(f"final answer non-empty (README-ESQL.md:{ln} pre-event checklist item 6)", len(answer.strip()) >= 20, f"{len(answer)} chars")
    check(f"agent made >=2 retrieval hops (README-ESQL.md:{ln}: 'converse shows >=2 retrieval hops')", len(hops) >= 2, f"{len(hops)} hops: {summary['hop_queries']}")
    check("second hop is a refined (different) query (DERIVED)", len(set(summary["hop_queries"])) >= 2, "")
    low = answer.lower()
    check("answer mentions exit code 137 / OOM or memory/heap settings (DERIVED, loose)", any(k in low for k in ("137", "oom", "heap", "xmx", "memory")), "")
else:
    print(json.dumps(res, indent=2)[:1500])

# ---------------------------------------------------------------- hop probe + model pinning
def hops_of(res):
    calls = [x for x in (res.get("steps") or []) if x.get("type") == "tool_call"]
    return len([c for c in calls if c.get("tool_id") == TOOL]), [c.get("tool_id") for c in calls]


if args.probe:
    print(f"\n== hop probe: {args.probe} fresh conversation(s) per question ==")
    QS = [("lab4", Q)]
    if args.alt:  # NOT in the notebook: derived from the symptoms named in setup_agent.py's skill description
        QS += [("alt-yellow", "My Elasticsearch cluster health is yellow. Why does that happen, and what exact setting or API call fixes it?"),
               ("alt-saml", "Users keep failing to log in with SAML. What causes it, and how do I fix and verify it?")]
    probe_out = []
    for tag, qtext in QS:
        for i in range(args.probe):
            body = {"agent_id": AGENT, "input": qtext}   # no conversation_id => fresh conversation
            if args.connector_id:
                body["connector_id"] = args.connector_id
            t0 = time.time()
            st2, r2, note2 = kb("POST", "/api/agent_builder/converse", body, timeout=420)
            rec = {"q": tag, "run": i + 1, "http": st2, "secs": round(time.time() - t0, 1)}
            if st2 == 200 and isinstance(r2, dict):
                n_hops, tools = hops_of(r2)
                rec.update({"retrieval_hops": n_hops, "all_tool_ids": tools, "model_usage": r2.get("model_usage"),
                            "top_level_keys": sorted(r2.keys()), "conversation_id": r2.get("conversation_id")})
            else:
                rec["error"] = str(r2)[:300]
            probe_out.append(rec)
            print(f"  {tag} run {i + 1}: " + json.dumps({k: v for k, v in rec.items() if k != "top_level_keys"})[:400])
    save("probe.json", probe_out)
    for tag, _ in QS:
        hs = [r_.get("retrieval_hops") for r_ in probe_out if r_["q"] == tag]
        print(f"  SUMMARY {tag}: retrieval_hops per run = {hs}")

# model pinning: look for connector/model/llm fields in the agent JSON and try a few listing endpoints
print("\n== can the agent pin a connector / LLM? ==")
def find_keys(o, path=""):
    out = []
    if isinstance(o, dict):
        for k, v in o.items():
            if any(w in k.lower() for w in ("connector", "model", "llm", "inference")):
                out.append((f"{path}/{k}", v if not isinstance(v, (dict, list)) else "<obj>"))
            out += find_keys(v, f"{path}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out += find_keys(v, f"{path}[{i}]")
    return out
agent_json = (agent if isinstance(agent, dict) else {})
print("  connector/model-like keys in GET agent:", find_keys(agent_json) or "none")
listing = {}
for path in ("/api/agent_builder/agents", "/api/agent_builder/connectors", "/api/agent_builder/llms", "/api/actions/connectors", "/api/agent_builder/settings"):
    st3, js3, _ = kb("GET", path, timeout=60)
    listing[path] = {"http": st3, "keys": sorted(js3.keys())[:20] if isinstance(js3, dict) else type(js3).__name__}
    if st3 == 200 and path == "/api/actions/connectors" and isinstance(js3, list):
        listing[path]["connectors"] = [{"id": c.get("id"), "name": c.get("name"), "type": c.get("connector_type_id"), "preconfigured": c.get("is_preconfigured")} for c in js3][:30]
    print(f"  GET {path}: HTTP {st3}")
save("model_pinning_probe.json", {"agent_model_keys": find_keys(agent_json), "listing": listing})

save("summary.json", {"summary": summary, "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]})
fails = [c for c in checks if not c[1]]
print(f"\n03_agent_builder: {len(checks) - len(fails)}/{len(checks)} checks passed; raw JSON in {OUTD}")
sys.exit(1 if fails else 0)
