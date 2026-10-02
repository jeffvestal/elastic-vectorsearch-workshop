#!/usr/bin/env bash
# Replays the Instruqt sandbox setup (01-esql-vector-search/setup-kubernetes-vm) against the cluster
# named by ES_ENDPOINT / ES_API_KEY / ES_KIBANA_URL.  Reads NOTHING but those env vars.
#
# WARNING: corpus/ingest.py DELETES and re-creates the index `aiewf-workshop-docs`, and
# agent-builder/setup_agent.py DELETES and re-creates the demo tool/skill/agent -- exactly like the
# sandbox does.  Set SKIP_INGEST=1 / SKIP_AGENT=1 to skip those mutating steps.
set -uo pipefail

HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HARNESS/venv/bin/python"
OUT="$HARNESS/out"
WORK="$HARNESS/work"
mkdir -p "$OUT"
FAILS=0
fail() { echo "FAIL: $*"; FAILS=$((FAILS+1)); }

for v in ES_ENDPOINT ES_API_KEY ES_KIBANA_URL; do
  if [ -z "${!v:-}" ]; then echo "ERROR: env var $v is not set"; exit 2; fi
done
ES_ENDPOINT="${ES_ENDPOINT%/}"; ES_KIBANA_URL="${ES_KIBANA_URL%/}"
export ES_ENDPOINT ES_KIBANA_URL ES_API_KEY
# Names the sandbox script / notebooks use for the Kibana URL:
export ES_KIBANA="$ES_KIBANA_URL"
export KIBANA_URL="$ES_KIBANA_URL"
echo "=== cluster hosts (values of credentials are never printed) ==="
echo "ES host:     $(echo "$ES_ENDPOINT" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"
echo "Kibana host: $(echo "$ES_KIBANA_URL" | sed -E 's#^[a-z]+://([^/:]+).*#\1#')"

echo; echo "=== Staging read-only sources into $WORK ==="
"$PY" "$HARNESS/lib/stage_sources.py" || { echo "staging failed"; exit 2; }

# ---------------------------------------------------------------------------
echo; echo "=== Ingesting corpus (copy of corpus/, cwd = corpus) ==="
if [ "${SKIP_INGEST:-0}" = "1" ]; then
  echo "SKIP_INGEST=1 -> not re-ingesting"
else
  ( cd "$WORK/corpus" && "$PY" ingest.py 2>&1 ) | tee "$OUT/00_ingest.log"
  [ "${PIPESTATUS[0]}" = "0" ] || fail "ingest.py exited non-zero"
fi

# ---------------------------------------------------------------------------
echo; echo "=== Creating Kibana data view (same curl as setup-kubernetes-vm) ==="
DV_HTTP=$(curl -s -o "$OUT/00_dv_resp.json" -w "%{http_code}" \
  -X POST "$ES_KIBANA_URL/api/data_views/data_view" \
  -H "Authorization: ApiKey $ES_API_KEY" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{"data_view": {"name": "aiewf-workshop-docs", "title": "aiewf-workshop-docs", "allowNoIndex": false}}' || true)
echo "data view HTTP status: $DV_HTTP" | tee "$OUT/00_dataview_http.txt"
if [ "$DV_HTTP" = "200" ] || [ "$DV_HTTP" = "201" ]; then
  echo "Data view 'aiewf-workshop-docs' created."
elif [ "$DV_HTTP" = "409" ]; then
  echo "Data view already exists -- OK."
else
  echo "WARNING: data view creation returned HTTP $DV_HTTP. Discover may show no data."
  head -c 600 "$OUT/00_dv_resp.json" 2>/dev/null; echo
  fail "data view creation HTTP $DV_HTTP (expected 200/201/409)"
fi
# Extra (not in the sandbox script): confirm the data view is actually listed.
curl -s -H "Authorization: ApiKey $ES_API_KEY" -H "kbn-xsrf: true" \
  "$ES_KIBANA_URL/api/data_views" -o "$OUT/00_dataviews_list.json" || true
if "$PY" - "$OUT/00_dataviews_list.json" <<'PYEOF'
import json, sys
try:
    js = json.load(open(sys.argv[1]))
    titles = [d.get("title") for d in js.get("data_view", [])]
    ok = "aiewf-workshop-docs" in titles
    print(f"data views visible via API: {len(titles)}; aiewf-workshop-docs listed: {ok}")
    sys.exit(0 if ok else 1)
except Exception as e:
    print("could not parse data view list:", type(e).__name__); sys.exit(1)
PYEOF
then :; else fail "aiewf-workshop-docs data view not listed by GET /api/data_views"; fi

# ---------------------------------------------------------------------------
echo; echo "=== Verifying a completion inference endpoint exists (same snippet as setup script) ==="
"$PY" - <<'PYEOF' 2>&1 | tee "$OUT/00_completion_check.log"
import os
from elasticsearch import Elasticsearch
es = Elasticsearch(os.environ["ES_ENDPOINT"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
eps = es.inference.get().body.get("endpoints", [])
comp = [e["inference_id"] for e in eps if e.get("task_type") == "completion"]
haiku = [e for e in comp if "haiku" in e]
if comp:
    print(f"  completion endpoints available ({len(comp)}). Lab 4 will use: "
          f"{haiku[0] if haiku else comp[0]}")
else:
    print("  WARNING: no completion-task endpoints found -- Lab 4 COMPLETION cells will fail.")
PYEOF
grep -q "completion endpoints available" "$OUT/00_completion_check.log" || fail "no completion-task endpoint"

# ---------------------------------------------------------------------------
echo; echo "=== Provisioning Lab 4 Agent Builder agent + tool (KIBANA_URL=\$ES_KIBANA_URL) ==="
if [ "${SKIP_AGENT:-0}" = "1" ]; then
  echo "SKIP_AGENT=1 -> not running setup_agent.py"
else
  ( cd "$WORK/agent-builder" && KIBANA_URL="$ES_KIBANA_URL" "$PY" setup_agent.py 2>&1 ) | tee "$OUT/00_setup_agent.log"
  [ "${PIPESTATUS[0]}" = "0" ] || fail "setup_agent.py exited non-zero"
  grep -q "Tool created" "$OUT/00_setup_agent.log" || fail "setup_agent: tool not created"
  grep -q "Agent created" "$OUT/00_setup_agent.log" || fail "setup_agent: agent not created"
  grep -q "Skill created" "$OUT/00_setup_agent.log" || echo "NOTE: skill not created (non-fatal in setup_agent.py)"
  grep -q "Tool smoke test: returned results" "$OUT/00_setup_agent.log" || fail "setup_agent: tool smoke test did not return results"
fi

# ---------------------------------------------------------------------------
echo; echo "=== Inference endpoints: dump (id + task_type only) and assert referenced ids exist ==="
"$PY" "$HARNESS/lib/inference_check.py" 2>&1 | tee "$OUT/00_inference_check.log"
[ "${PIPESTATUS[0]}" = "0" ] || fail "inference id check"

# ---------------------------------------------------------------------------
echo; echo "=== Doc count must be 62 ==="
COUNT=$("$PY" - <<'PYEOF'
import os
from elasticsearch import Elasticsearch
es = Elasticsearch(os.environ["ES_ENDPOINT"], api_key=os.environ["ES_API_KEY"], request_timeout=60)
print(es.count(index="aiewf-workshop-docs")["count"])
PYEOF
)
echo "doc count: ${COUNT:-<error>}" | tee "$OUT/00_doc_count.txt"
if [ "${COUNT:-}" = "62" ]; then echo "doc count OK (62)"; else fail "doc count is '${COUNT:-error}', expected 62"; fi

echo
if [ "$FAILS" -eq 0 ]; then echo "00_setup_like_sandbox: PASS"; else echo "00_setup_like_sandbox: FAIL ($FAILS problem(s))"; fi
exit $(( FAILS > 0 ? 1 : 0 ))
