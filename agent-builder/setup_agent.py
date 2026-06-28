#!/usr/bin/env python3
"""
Provision the Lab 4 "Part 3" Agent Builder demo: a hybrid-retrieval tool and a
multi-hop agent, created via the Kibana Agent Builder REST API.

This is the same hybrid retriever the workshop built in Lab 3 — BM25 + semantic,
fused with RRF — expressed as a single ES|QL statement (FORK ... FUSE) and wrapped
as an Agent Builder tool. The agent calls that tool and decides on its own whether a
second retrieval hop is needed. No hand-rolled agent loop; Agent Builder runs the loop.

Idempotent: deletes any existing tool/agent with the same IDs first, then recreates.
Run it again any time to reset to a known-good state.

Usage:
    ES_ENDPOINT=https://...es...:443  \
    ES_API_KEY=...                    \
    KIBANA_URL=https://...kb...:443   \
    python setup_agent.py

Notes:
- KIBANA_URL is the Kibana endpoint (".kb."), NOT the Elasticsearch endpoint (".es.").
  Agent Builder is a Kibana API. In the Instruqt sandbox both are agent variables.
- The API key needs the `manage_onechat` Kibana privilege for writes. The sandbox's
  managed key already has it.
- Requires only the Python standard library (urllib) — no extra pip installs.
"""

import json
import os
import sys
import urllib.error
import urllib.request

# ─── Configuration ────────────────────────────────────────────────────────────

KIBANA_URL = os.environ.get("KIBANA_URL")
ES_API_KEY = os.environ.get("ES_API_KEY")

INDEX = "aiewf-workshop-docs"
TOOL_ID = "search-workshop-docs-hybrid"
AGENT_ID = "workshop-docs-agent"
SKILL_ID = "workshop-docs-diagnose-fix"

# The Lab 3 hybrid retriever as one ES|QL statement.
#   FORK runs two sub-queries — a BM25 `match` on `body` and a semantic `match` on
#   `body_semantic` — each capped at 50 candidates, then FUSE applies RRF over the two
#   ranked lists. This returns the *identical* ranking to the `_search` `rrf` retriever
#   the notebooks use (verified: doc-049 #1 on "notify me when something goes wrong").
# `?query` is an Agent Builder tool parameter, bound at call time and used in both arms.
HYBRID_ESQL = (
    "FROM aiewf-workshop-docs METADATA _score, _id, _index\n"
    "| FORK ( WHERE match(body, ?query) | SORT _score DESC | LIMIT 50 )\n"
    "       ( WHERE match(body_semantic, ?query) | SORT _score DESC | LIMIT 50 )\n"
    "| FUSE\n"
    "| SORT _score DESC\n"
    "| KEEP id, title, url, body, _score\n"
    "| LIMIT 5"
)

TOOL_BODY = {
    "id": TOOL_ID,
    "type": "esql",
    "description": (
        "Hybrid (BM25 + semantic) search over the Elasticsearch documentation corpus, "
        "fused with RRF. Use this to find relevant docs for ANY question about "
        "Elasticsearch — error codes, version notes, config keys, or natural-language "
        "'how do I' questions. Returns id, title, url, and body for the top 5 docs. "
        "Call it again with a refined query if the first results don't fully answer the "
        "question."
    ),
    "tags": ["workshop", "search", "hybrid", "rag"],
    "configuration": {
        "query": HYBRID_ESQL,
        "params": {
            "query": {
                "type": "string",
                "description": (
                    "The natural-language search query or keywords to find "
                    "documentation for."
                ),
            }
        },
    },
}

# A SKILL specializes the agent for a recurring task. This one is a diagnose-and-fix
# playbook matching the lab's two-part demo questions (symptom → cause → fix). It
# references the same hybrid tool, and gets attached to the agent via skill_ids below.
SKILL_CONTENT = """# Diagnose & Fix playbook

When the user reports an Elasticsearch symptom and wants both *why it happens* and *how to fix it*, work in this order:

1. **Find the cause.** Search the symptom (the error code, the cluster state, the failure) with `search-workshop-docs-hybrid` to identify the root cause.
2. **Find the fix.** The first results usually point at a specific API, setting, or subsystem. Run a SECOND search targeting that fix — the exact setting name, the repair API, the config key.
3. **Answer as Cause → Fix → Citations.**
   - **Cause:** one or two sentences on what's actually wrong.
   - **Fix:** the concrete steps, naming the exact settings, commands, or API calls from the docs.
   - **Citations:** the doc titles you used, as [title].

Never guess a setting name or a command — if the docs don't contain it, say so."""

SKILL_BODY = {
    "id": SKILL_ID,
    "name": "Diagnose & Fix",
    "description": (
        "Use when the user reports an Elasticsearch symptom (error code, yellow cluster, "
        "failed login) and wants both the cause and the fix. Drives a two-search "
        "diagnose-then-repair flow and answers as Cause -> Fix -> Citations."
    ),
    "content": SKILL_CONTENT,
    "tool_ids": [TOOL_ID],
}

# The agent's system prompt is what turns one tool into a multi-hop agent. The
# numbered "How you work" steps tell the model to retrieve, read, and run a SECOND
# focused search when the first results point at a gap (a setting, a root cause, a
# related subsystem) before answering. Agent Builder executes that loop natively.
AGENT_INSTRUCTIONS = """You are an Elasticsearch documentation assistant built on hybrid retrieval.

## Your tool
- **search-workshop-docs-hybrid**: hybrid (BM25 + semantic, RRF-fused) search over the Elasticsearch docs corpus. It returns the top 5 docs with id, title, url, and body.

## How you work (multi-hop)
1. Call `search-workshop-docs-hybrid` with the user's question to get an initial set of docs.
2. Read the results. If they fully answer the question, write the answer.
3. If answering well requires a fact the first results point to but don't fully cover (a setting, a root cause, a related subsystem), run a SECOND search with a refined query targeting that specific gap, then answer from the combined results. Prefer one focused follow-up over many.
4. Ground every claim in retrieved docs. Cite sources as [title]. If the docs don't contain the answer, say so — do not guess.

## Style
Concise and technical. Use short sections or bullets. Name the specific settings, codes, or commands the docs mention."""

AGENT_BODY = {
    "id": AGENT_ID,
    "name": "Workshop Docs Agent",
    "description": (
        "Multi-hop RAG agent over the AIEWF workshop docs corpus, powered by hybrid "
        "retrieval."
    ),
    "labels": ["workshop"],
    "configuration": {
        "instructions": AGENT_INSTRUCTIONS,
        "tools": [{"tool_ids": [TOOL_ID]}],
        # skill_ids attaches the Diagnose & Fix skill to this agent (a skill is not
        # active on an agent until explicitly added). If a given Serverless build
        # doesn't accept skill_ids yet, create_agent still succeeds without it and the
        # skill can be attached in the Kibana UI (Customize -> Skills).
        "skill_ids": [SKILL_ID],
    },
}

# ─── HTTP helpers (stdlib only) ───────────────────────────────────────────────


def _req(method, path, body=None):
    url = f"{KIBANA_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"ApiKey {ES_API_KEY}",
            "kbn-xsrf": "true",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500]}


def _delete_quiet(path):
    """Delete, ignoring 404s — makes the script idempotent/re-runnable."""
    status, _ = _req("DELETE", path)
    return status


def _without_skill(agent_body):
    """Return a copy of the agent body with skill_ids stripped — fallback for builds
    that don't accept it yet, so agent creation still succeeds."""
    body = json.loads(json.dumps(agent_body))
    body["configuration"].pop("skill_ids", None)
    return body


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    if not KIBANA_URL or not ES_API_KEY:
        sys.exit(
            "Set KIBANA_URL and ES_API_KEY.\n"
            "  KIBANA_URL is the Kibana endpoint (.kb.), not Elasticsearch (.es.).\n"
            "  In Instruqt: both are pre-configured sandbox variables."
        )

    print(f"Kibana: {KIBANA_URL}")
    print(f"Index:  {INDEX}\n")

    # Reset (idempotent): delete in dependency order — the agent references both the
    # skill (skill_ids) and the tool, and the skill references the tool, so the agent
    # must go first, then the skill, then the tool.
    print("Resetting any existing demo objects...")
    _delete_quiet(f"/api/agent_builder/agents/{AGENT_ID}")
    _delete_quiet(f"/api/agent_builder/skills/{SKILL_ID}")
    _delete_quiet(f"/api/agent_builder/tools/{TOOL_ID}")

    # 1. Create the hybrid retrieval tool
    status, resp = _req("POST", "/api/agent_builder/tools", TOOL_BODY)
    if status != 200:
        sys.exit(f"✗ Tool create failed ({status}): {resp.get('error', resp)}")
    print(f"✓ Tool created:  {TOOL_ID}")

    # 2. Create the Diagnose & Fix skill (references the tool above)
    status, resp = _req("POST", "/api/agent_builder/skills", SKILL_BODY)
    skill_ok = status == 200
    if skill_ok:
        print(f"✓ Skill created: {SKILL_ID}")
    else:
        # Non-fatal: some Serverless builds may not expose the skills API yet. The agent
        # still works; the skill can be created/attached later in the Kibana UI.
        print(f"⚠ Skill create skipped ({status}): {resp.get('error', resp)}")

    # 3. Create the multi-hop agent wired to the tool (+ skill via skill_ids)
    agent_body = AGENT_BODY if skill_ok else _without_skill(AGENT_BODY)
    status, resp = _req("POST", "/api/agent_builder/agents", agent_body)
    if status != 200 and skill_ok:
        # If skill_ids was the problem, retry once without it so the agent still lands.
        print(f"⚠ Agent create with skill_ids failed ({status}); retrying without it...")
        status, resp = _req("POST", "/api/agent_builder/agents", _without_skill(AGENT_BODY))
    if status != 200:
        sys.exit(f"✗ Agent create failed ({status}): {resp.get('error', resp)}")
    print(f"✓ Agent created: {AGENT_ID}")

    # 4. Smoke-test the tool returns hybrid results
    status, resp = _req(
        "POST",
        "/api/agent_builder/tools/_execute",
        {"tool_id": TOOL_ID, "tool_params": {"query": "notify me when something goes wrong"}},
    )
    ok = status == 200
    print(f"{'✓' if ok else '✗'} Tool smoke test: {'returned results' if ok else resp.get('error', resp)}")

    print("\nDone. Open Agent Builder in Kibana and chat with 'Workshop Docs Agent':")
    print(f"  {KIBANA_URL}/app/agent_builder")


if __name__ == "__main__":
    main()
