# ES|QL workshop test harness

Tests the ES|QL edition of "Vector -> Hybrid -> Do You Even Need a Model?" the way an attendee meets it.
Credentials come ONLY from env vars (never read from files, never printed):

    export ES_ENDPOINT=https://...es...  ES_API_KEY=...  ES_KIBANA_URL=https://...kb...
    ./run_all.sh            # 00..04 in order, log -> out/run_all.log   (SKIP_INGEST=1 SKIP_AGENT=1 SKIP_UI=1 to trim)

**Destructive on the target cluster, exactly like sandbox boot:** `ingest.py` deletes/recreates index `aiewf-workshop-docs`;
`setup_agent.py` and Lab 4 cell 12 delete/recreate the demo tool, skill and agent. Use a throwaway project.

| Script | What it checks | Output (all under `out/`) |
|---|---|---|
| `00_setup_like_sandbox.sh` | Replays `setup-kubernetes-vm`: ingest (from a copy in `work/`), Kibana data view POST (reports HTTP code, then confirms it is listed), completion-endpoint check, `setup_agent.py` with `KIBANA_URL=$ES_KIBANA_URL`, `GET _inference/_all` (id + task_type only), asserts every inference id found by regex in notebooks/assignments exists with the right task_type, asserts doc count == 62. | `00_*.log`, `inference_endpoints.json` |
| `01_run_notebooks.py` | Executes the 5 notebooks with nbclient (venv kernel, 300 s/cell, `allow_errors`), env passed through (`KIBANA_URL` derived from `ES_KIBANA_URL`). Prints cells run / errored (cell index + first 3 traceback lines). `--only lab3 lab4`, `--timeout N`. | `executed/*.ipynb`, `executed/*.txt` (all text outputs), `executed/images/`, `notebooks_summary.json` |
| `02_assert_claims.py` | ~105 ES|QL assertions via `POST /_query` (trap-rank table, Lab 3 linear 0.8/0.2 vs 0.3/0.7, RRF #1 x6, filter, RERANK+SORT, COMPLETION good/bad, Lab 5 rerankers, quirks) **plus every ```esql block of every assignment.md run verbatim** (and the "swap X for Y" variants) and every full-query block in the notebook markdown. Each assertion cites file:line of its source. Levels: EXACT / CLAIM / LABTEXT gate the exit code; DERIVED / INFO do not. | `claims.md` (pass/fail table, failures with actual top-5), `claims_raw.json` |
| `03_agent_builder.py` | Kibana API: GET tool `search-workshop-docs-hybrid`, agent `workshop-docs-agent`, skill; tool `_execute` smoke test; `POST /api/agent_builder/converse {agent_id, input}` with the Lab 4 two-part question (read from the notebook). Reports tool calls / retrieval hops (expects >= 2) and the final answer. Retries once with `x-elastic-internal-origin: Kibana`. | `agent/*.json`, `agent/converse_answer.txt` |
| `04_ui_playwright.py` | Chromium 1600x1000. API key header added by `page.route` only on the Kibana host. Aborts clearly on a login page. Discover: data-view selector, switch to ES|QL (adaptive; also checks the lab's "KQL/Lucene -> ES|QL" switcher claim), paste Lab 1 query 1 (expects 62) and 2 (expects doc-010). Agent Builder: find "Workshop Docs Agent", send Lab 4 question, wait <= 120 s, screenshot tool-call display. `--headed --skip-agent --skip-discover --wait N`. | `ui/run-<ts>/NN-*.png`, `ui/run-<ts>/ui_log.json` (step -> ok/error/notes, visible-text hints, Kibana 4xx/5xx paths) |

`lib/` = shared helpers (`common.py`), `stage_sources.py`, `inference_check.py`. `work/` = staged read-only copies of the
workshop sources (explicit file list only; no dotfiles). `venv/` pins `elasticsearch>=8.17,<9 jupyter requests matplotlib`
(sandbox pins) + nbclient nbformat playwright pyyaml. Override source locations with `WORKSHOP_DIR` / `ASSIGNMENT_DIR`.

Status: written and syntax-checked only; the code paths were smoke-tested against local stub servers, never against a real cluster.

## Setup (fresh clone)
    python3 -m venv venv && venv/bin/pip install 'elasticsearch>=8.17,<9' jupyter requests matplotlib nbclient nbformat playwright pyyaml
    venv/bin/playwright install chromium
`05_agent_direct.py`, `06_agent_steps.py`, `07_agent_model_switch.py` are ad-hoc Agent Builder UI probes from the
2026-10-02 pass (direct agent URL, execution-details panel, switching the chat model to Claude Sonnet 4.5).
