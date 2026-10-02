#!/usr/bin/env bash
# Runs the whole harness in order using the harness venv. Reads nothing but env vars:
#   ES_ENDPOINT  ES_API_KEY  ES_KIBANA_URL      (optional: SKIP_INGEST=1  SKIP_AGENT=1  SKIP_UI=1)
# Every stage runs even if an earlier one fails (they report independently); exit code = number of failed stages.
set -uo pipefail
HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HARNESS/venv/bin/python"
mkdir -p "$HARNESS/out"
for v in ES_ENDPOINT ES_API_KEY ES_KIBANA_URL; do
  [ -n "${!v:-}" ] || { echo "ERROR: env var $v is not set"; exit 2; }
done
[ -x "$PY" ] || { echo "ERROR: venv missing at $HARNESS/venv"; exit 2; }

{
  echo "######## harness run started $(date '+%Y-%m-%d %H:%M:%S') ########"
  declare -a NAMES=() CODES=()
  stage() { # name, command...
    local name="$1"; shift
    echo; echo "================ $name ================"
    "$@"; local rc=$?
    NAMES+=("$name"); CODES+=("$rc")
    echo "---- $name exit code: $rc"
  }
  stage "00 setup like sandbox"   bash "$HARNESS/00_setup_like_sandbox.sh"
  stage "01 run notebooks"        "$PY" "$HARNESS/01_run_notebooks.py"
  stage "02 assert claims"        "$PY" "$HARNESS/02_assert_claims.py"
  stage "03 agent builder"        "$PY" "$HARNESS/03_agent_builder.py"
  if [ "${SKIP_UI:-0}" = "1" ]; then echo "SKIP_UI=1 -> skipping 04"; else
    stage "04 ui playwright"      "$PY" "$HARNESS/04_ui_playwright.py"
  fi
  echo; echo "================ SUMMARY ================"
  FAILED=0
  for i in "${!NAMES[@]}"; do
    if [ "${CODES[$i]}" = "0" ]; then s=PASS; else s="FAIL(${CODES[$i]})"; FAILED=$((FAILED+1)); fi
    printf '  %-28s %s\n' "${NAMES[$i]}" "$s"
  done
  echo "  claims table:      $HARNESS/out/claims.md"
  echo "  notebook outputs:  $HARNESS/out/executed/"
  echo "  agent JSON:        $HARNESS/out/agent/"
  echo "  UI screenshots:    $HARNESS/out/ui/"
  exit $FAILED
} 2>&1 | tee "$HARNESS/out/run_all.log"
exit "${PIPESTATUS[0]}"
