#!/usr/bin/env python3
"""Playwright (chromium, headless, 1600x1000) walk-through of what an attendee does in Kibana.

Auth: page.route("**/*") adds `Authorization: ApiKey $ES_API_KEY` ONLY to requests whose URL host equals the
Kibana host (never to CDNs / other hosts).  Env used: ES_API_KEY, ES_KIBANA_URL, ES_ENDPOINT (unused).

Steps (each in try/except, screenshot after each -> out/ui/run-<timestamp>/NN-name.png, JSON log -> out/ui/ui_log.json):
  00 auth/landing check (aborts with a clear message on a login page)
  01 Discover landing
  02 data view selector (lab text: "Top-left, click the data view selector and choose aiewf-workshop-docs")
  03 switch to ES|QL mode (adaptive; records which control worked / what exists; also checks the lab's
     "KQL/Lucene -> ES|QL" language-switcher claim)
  04 paste Lab 1 query #1 (STATS COUNT(*)) and run;  05 Lab 1 query #2 (semantic MATCH) and run
  06 Agent Builder landing; 07 find 'Workshop Docs Agent'; 08 send lab 4 two-part question, wait <=120s; 09 tool-call display
Flags: --headed  --skip-agent  --skip-discover  --wait N (agent answer wait seconds, default 120)
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import common  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--headed", action="store_true")
ap.add_argument("--skip-agent", action="store_true")
ap.add_argument("--skip-discover", action="store_true")
ap.add_argument("--wait", type=int, default=150)
args = ap.parse_args()

common.require_env(("ES_API_KEY", "ES_KIBANA_URL"))
common.stage_sources()
KB = os.environ["ES_KIBANA_URL"]
KEY = os.environ["ES_API_KEY"]
KB_HOST = common.host_of(KB)
UI = common.OUT / "ui" / time.strftime("run-%Y%m%d-%H%M%S")   # per-run dir: never overwrites earlier evidence
UI.mkdir(parents=True, exist_ok=True)

# Lab 1 queries exactly as in 01-esql-vector-search/assignment.md (first two ```esql blocks)
asg1 = (common.WORK / "assignments" / "01-esql-vector-search" / "assignment.md").read_text(encoding="utf-8")
blocks = re.findall(r"```esql\n(.*?)\n```", asg1, re.S)
Q1, Q2 = blocks[0], blocks[1]
QUESTION = common.LAB4_AGENT_QUESTION
try:  # prefer the exact text in the notebook
    import ast
    nb = json.load(open(common.WORK / "notebooks-esql" / "lab4-esql-rag-pipeline.ipynb"))
    for c in nb["cells"]:
        s = "".join(c["source"])
        if c["cell_type"] == "code" and "agent_question" in s:
            for node in ast.walk(ast.parse(s)):
                if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "agent_question":
                    QUESTION = ast.literal_eval(node.value)
except Exception:  # noqa: BLE001
    pass

LOG = {"kibana_host": KB_HOST, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": [], "aborted": None,
       "http_errors_on_kibana_host": [], "console_errors": []}
_n = [0]


def write_log():
    (UI / "ui_log.json").write_text(json.dumps(LOG, indent=2, default=str))


def lit_(t):
    return '"' + t.replace('\\', '\\\\').replace('"', '\\"') + '"'


def hints(page, extra_selectors=()):
    """Visible-text hints: body text head, button/link labels, data-test-subj samples."""
    h = {"url": page.url}
    try:
        txt = page.inner_text("body", timeout=5000)
        h["body_text_head"] = re.sub(r"\s+", " ", txt)[:700]
    except Exception as e:  # noqa: BLE001
        h["body_text_head"] = f"<unavailable: {type(e).__name__}>"
    try:
        h["buttons"] = page.evaluate("""() => [...document.querySelectorAll('button,[role=button],a[role=tab],[role=menuitem],[role=option]')]
            .filter(e => e.offsetParent !== null).map(e => (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim().replace(/\\s+/g,' ').slice(0,50))
            .filter(Boolean).slice(0, 70)""")
        h["data_test_subj_sample"] = page.evaluate("""() => [...new Set([...document.querySelectorAll('[data-test-subj]')].map(e => e.getAttribute('data-test-subj')))]
            .filter(s => /esql|es-ql|text-based|language|dataview|data-view|agent|chat|conversation|query|run|submit|send/i.test(s)).slice(0, 60)""")
    except Exception:  # noqa: BLE001
        pass
    return h


def shot(page, name, full=False):
    _n[0] += 1
    fn = UI / f"{_n[0]:02d}-{name}.png"
    try:
        page.screenshot(path=str(fn), full_page=full)
    except Exception as e:  # noqa: BLE001
        return f"<screenshot failed: {type(e).__name__}>"
    return str(fn.relative_to(common.HARNESS))


def run_step(page, name, fn):
    t0 = time.time()
    rec = {"step": name, "status": "ok", "notes": {}, "screenshot": None}
    try:
        notes = fn() or {}
        rec["notes"] = notes
        if notes.get("_status"):
            rec["status"] = notes.pop("_status")
    except Exception as e:  # noqa: BLE001
        rec["status"] = "error"
        rec["notes"] = {"error": f"{type(e).__name__}: {str(e)[:400]}"}
    rec["screenshot"] = shot(page, name + ("" if rec["status"] != "error" else "-ERROR"))
    rec["hints"] = hints(page)
    rec["secs"] = round(time.time() - t0, 1)
    LOG["steps"].append(rec)
    write_log()
    print(f"[{rec['status']:<7}] {name:<28} {json.dumps(rec['notes'], default=str)[:200]}", flush=True)
    return rec


def click_first(page, locators, timeout=2500):
    """Try each (label, locator); click the first visible one. Returns label or None."""
    for label, loc in locators:
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=timeout)
                return label
        except Exception:  # noqa: BLE001
            continue
    return None


def dismiss_overlays(page):
    done = []
    for _ in range(3):
        hit = click_first(page, [
            ("skip-tour", page.get_by_role("button", name=re.compile(r"^(skip( tour| all)?|dismiss|got it|not now|no thanks|maybe later|close)$", re.I))),
            ("flyout-close", page.locator('[data-test-subj="euiFlyoutCloseButton"]')),
            ("toast-close", page.locator('[data-test-subj="toastCloseButton"]')),
        ], timeout=1500)
        if not hit:
            break
        done.append(hit)
        page.wait_for_timeout(500)
    return done


def esql_mode_active(page):
    return page.locator('[data-test-subj="ESQLEditor"], [data-test-subj="ESQLEditor-run-query-button"], '
                        '[data-test-subj="ESQLEditor-toggle-query-history-button"]').count() > 0


def settle(page, t=30000):
    try:
        page.wait_for_load_state("networkidle", timeout=t)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)


def editor_text(page):
    try:
        return re.sub(r"\s+", " ", page.locator(".monaco-editor .view-lines").first.inner_text(timeout=3000))
    except Exception:  # noqa: BLE001
        return ""


SELECT_ALL = "Meta+A" if sys.platform == "darwin" else "Control+A"


def norm(t):
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def set_editor(page, query, must_contain=None):
    """Focus the Monaco editor by clicking INSIDE .view-lines, then replace its text and verify equality.

    Order: (1) monaco model setValue via page.evaluate if window.monaco is exposed,
           (2) platform select-all (Meta+A on macOS) while the editor has focus + insert_text,
           (3) same select-all + typing a single-line version.
    Returns the method name that produced text equal to the query (whitespace-normalised), else None.
    NOTE: Control+K/Cmd+K-style chords are never sent; select-all is only pressed after the click.
    """
    want = norm(query)
    page.locator(".monaco-editor .view-lines").first.click(timeout=5000)
    page.wait_for_timeout(300)
    # (1) monaco API
    try:
        ok = page.evaluate("""q => { try { const m = window.monaco && window.monaco.editor; if (!m) return false;
            const models = m.getModels(); if (!models.length) return false; models[0].setValue(q); return true; } catch (e) { return false; } }""", query)
        if ok:
            page.wait_for_timeout(500)
            if norm(editor_text(page)) == want:
                return "monaco.setValue"
    except Exception:  # noqa: BLE001
        pass
    for method in ("select-all+insert_text", "select-all+type"):
        page.locator(".monaco-editor .view-lines").first.click(timeout=5000)
        page.keyboard.press(SELECT_ALL)
        page.keyboard.press("Delete")
        if method.endswith("insert_text"):
            page.keyboard.insert_text(query)
        else:
            page.keyboard.type(" ".join(query.split()), delay=8)
        page.wait_for_timeout(600)
        page.keyboard.press("Escape")          # close autocomplete without accepting
        if norm(editor_text(page)) == want:
            return method
    return None


def grid_text(page):
    grid = page.locator('[data-test-subj="discoverDocTable"], [data-test-subj="docTable"], [data-test-subj="euiDataGridBody"], [role="grid"]')
    try:
        return re.sub(r"\s+", " ", grid.first.inner_text(timeout=4000))
    except Exception:  # noqa: BLE001
        return ""


def run_query(page, expect=None, max_wait=60):
    how = click_first(page, [
        ("Search button (querySubmitButton)", page.locator('[data-test-subj="querySubmitButton"], [data-test-subj="ESQLEditor-run-query-button"]')),
        ("button 'Search'", page.get_by_role("button", name=re.compile(r"^search$", re.I))),
        ("button 'Run/Update/Refresh'", page.get_by_role("button", name=re.compile(r"^(\u25b6\s*)?(run|update|refresh)", re.I))),
    ])
    if not how:
        page.keyboard.press("ControlOrMeta+Enter")
        how = "keyboard ControlOrMeta+Enter"
    settle(page, 30000)
    t0 = time.time()
    txt = ""
    while time.time() - t0 < max_wait:
        txt = grid_text(page)
        if txt and (expect is None or expect in txt):
            break
        page.wait_for_timeout(2000)
    err = ""
    try:
        err = " | ".join(re.sub(r"\s+", " ", t)[:200] for t in page.locator('.euiCallOut--danger, [data-test-subj*="error" i]').all_inner_texts()[:3])
    except Exception:  # noqa: BLE001
        pass
    return how, txt, err


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        )
        try:
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=KB)
        except Exception:  # noqa: BLE001
            pass

        def handler(route, request):
            try:
                if common.host_of(request.url) == KB_HOST:      # ONLY the Kibana host gets the key
                    hdrs = dict(request.headers)
                    hdrs["authorization"] = f"ApiKey {KEY}"
                    route.continue_(headers=hdrs)
                else:
                    route.continue_()
            except Exception:  # noqa: BLE001
                try:
                    route.continue_()
                except Exception:  # noqa: BLE001
                    pass

        ctx.route("**/*", handler)
        page = ctx.new_page()
        seen = set()

        def on_resp(resp):
            try:
                if resp.status >= 400 and common.host_of(resp.url) == KB_HOST:
                    key = (resp.status, re.sub(r"\?.*", "", resp.url.replace(KB, ""))[:120])
                    if key not in seen and len(seen) < 40:
                        seen.add(key)
                        LOG["http_errors_on_kibana_host"].append({"status": key[0], "path": key[1]})
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_resp)
        page.on("console", lambda m: LOG["console_errors"].append(m.text[:200]) if m.type == "error" and len(LOG["console_errors"]) < 15 else None)

        # ---------------- 00 auth / landing check ----------------
        def auth_check():
            page.goto(f"{KB}/app/discover", wait_until="domcontentloaded", timeout=90000)
            settle(page, 45000)
            url, txt = page.url, ""
            try:
                txt = page.inner_text("body", timeout=5000)
            except Exception:  # noqa: BLE001
                pass
            login = ("/login" in url) or page.locator('input[type="password"], input[name="username"]').count() > 0 \
                or re.search(r"(log in to|sign in to|welcome to elastic)", txt, re.I) is not None
            upgrade = "upgrade your browser" in txt.lower()
            out = {"final_url": url, "login_page_detected": bool(login), "upgrade_browser_message": upgrade,
                   "dismissed": dismiss_overlays(page)}
            if login or upgrade:
                out["_status"] = "ABORT"
                LOG["aborted"] = ("AUTH FAILED: Kibana served a login page (ApiKey header was not accepted for browser navigation). "
                                  if login else "Kibana showed 'Please upgrade your browser' (CSP / browser check) - cannot continue. ")
            return out

        r = run_step(page, "auth-landing-check", auth_check)
        if LOG["aborted"]:
            print("\nABORT:", LOG["aborted"], "\nSee out/ui/ screenshots and ui_log.json.")
            browser.close()
            write_log()
            return 3

        if not args.skip_discover:
            # ---------------- 01 Discover landing: record the NEW serverless UI facts ----------------
            def discover_landing():
                page.goto(f"{KB}/app/discover", wait_until="domcontentloaded", timeout=90000)
                settle(page, 45000)
                n = {"dismissed": dismiss_overlays(page), "esql_editor_present": page.locator(".monaco-editor").count() > 0}
                n["default_query_text"] = editor_text(page)[:120]
                n["switch_to_classic_button"] = page.get_by_text("Switch to Classic").count() > 0
                n["dataview_selector_present (lab text expects one)"] = page.locator('[data-test-subj="discover-dataView-switch-link"]').count() > 0
                n["kql_lucene_language_switcher_present (lab text expects one)"] = page.locator('[data-test-subj="switchQueryLanguageButton"]').count() > 0
                n["search_button_present"] = page.get_by_role("button", name=re.compile(r"^search$", re.I)).count() > 0
                n["new_session_tab"] = page.get_by_text("New session").count() > 0
                return n

            run_step(page, "discover-landing", discover_landing)

            asg = {k: (common.WORK / "assignments" / d / "assignment.md").read_text(encoding="utf-8")
                   for k, d in zip((1, 2, 3, 4), common.LAB_DIRS)}
            blk = {k: re.findall(r"```esql\n(.*?)\n```", v, re.S) for k, v in asg.items()}
            lab4_q = common.LAB4_RAG_QUESTION
            DQ = [  # (step name, query exactly as the assignment shows it, text expected in the results grid, max wait s)
                ("lab1-q1-count", blk[1][0], "62", 60),
                ("lab1-q2-semantic", blk[1][1], "doc-010", 90),
                ("lab2-trap-bm25-exit-code-137", blk[2][1], "doc-061", 90),
                ("lab3-rrf-fork-fuse", blk[3][0], "doc-049", 90),
                ("lab4-peek-headline", blk[4][0].replace("?q", lit_(lab4_q)), "doc-017", 150),
            ]
            for name, q, expect, mw in DQ:
                def do_query(q=q, expect=expect, mw=mw):
                    if page.locator(".monaco-editor").count() == 0:
                        page.goto(f"{KB}/app/discover", wait_until="domcontentloaded")
                        settle(page, 30000)
                    method = set_editor(page, q)
                    n = {"editor_input_method": method, "editor_text_head": editor_text(page)[:160]}
                    if method is None:
                        n["_status"] = "FAIL-editor-text-not-equal-to-query"
                        return n
                    shot(page, name + "-typed")
                    how, gt, err = run_query(page, expect, mw)
                    ids = list(dict.fromkeys(re.findall(r"doc-\d{3}", gt)))
                    n.update({"run_via": how, "visible_doc_ids_in_order": ids, "results_text_head": gt[:500], "error_text": err,
                              f"expected_{expect!r}_visible": expect in gt})
                    if expect not in gt:
                        n["_status"] = "FAIL-expected-text-missing"
                    return n

                run_step(page, name, do_query)

        # ---------------- Agent Builder (new UI: left-nav "Agents"; sidebar has an agent dropdown) ----------------
        if not args.skip_agent:
            def ab_landing():
                path = []
                page.goto(f"{KB}/app/agent_builder", wait_until="domcontentloaded", timeout=90000)
                settle(page, 45000)
                n = {"dismissed": dismiss_overlays(page), "landed_url_path": page.url.replace(KB, ""),
                     "left_nav_items": [], "sidebar_agent_selector_text": None}
                try:
                    n["left_nav_items"] = page.evaluate("""() => [...document.querySelectorAll('nav a, nav button, [data-test-subj*="nav" i]')]
                        .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' ')).filter(Boolean).slice(0, 40)""")
                except Exception:  # noqa: BLE001
                    pass
                sel = page.get_by_role("button", name=re.compile(r"elastic ai agent", re.I))
                n["sidebar_agent_selector_text"] = sel.first.inner_text() if sel.count() else None
                n["has_manage_components"] = page.get_by_text("Manage components").count() > 0
                shot(page, "left-nav", full=False)
                return n

            run_step(page, "agent-builder-landing", ab_landing)

            path = []
            state = {"found": False}

            def find_agent():
                n = {"click_path": path}
                # A) sidebar agent dropdown ("Elastic AI Agent v")
                sel = page.get_by_role("button", name=re.compile(r"elastic ai agent", re.I))
                if sel.count():
                    sel.first.click(timeout=4000)
                    path.append("click sidebar header dropdown 'Elastic AI Agent'")
                    page.wait_for_timeout(1500)
                    shot(page, "agent-dropdown-open")
                    box = page.locator('input[type="search"], [role="combobox"] input, input[placeholder*="earch" i]')
                    if box.count():
                        box.first.fill("Workshop")
                        path.append("type 'Workshop' in the dropdown search box")
                        page.wait_for_timeout(1500)
                    t = page.get_by_text(re.compile(r"Workshop Docs Agent", re.I))
                    n["agent_visible_in_dropdown"] = t.count() > 0
                    if t.count():
                        t.first.click(timeout=4000)
                        path.append("click 'Workshop Docs Agent' in the dropdown")
                        state["found"] = True
                if not state["found"]:
                    # B) Manage components > Agents list with search box
                    mc = page.get_by_text("Manage components")
                    if mc.count():
                        mc.first.click(timeout=4000)
                        path.append("click 'Manage components' (bottom of sidebar)")
                        page.wait_for_timeout(1000)
                    ag = page.get_by_role("link", name=re.compile(r"^agents$", re.I))
                    if ag.count():
                        ag.first.click(timeout=4000)
                        path.append("click 'Agents'")
                        settle(page, 20000)
                    else:
                        page.goto(f"{KB}/app/agent_builder/agents", wait_until="domcontentloaded")
                        path.append("goto /app/agent_builder/agents (direct URL)")
                        settle(page, 20000)
                    box = page.locator('input[type="search"], input[placeholder*="earch" i]')
                    n["agents_list_search_box_present"] = box.count() > 0
                    if box.count():
                        box.first.fill("Workshop")
                        path.append("type 'Workshop' in the agents list search box")
                        page.wait_for_timeout(2000)
                    shot(page, "agents-list-filtered")
                    t = page.get_by_text(re.compile(r"Workshop Docs Agent", re.I))
                    n["agent_visible_in_list"] = t.count() > 0
                    if t.count():
                        t.first.click(timeout=4000)
                        path.append("click the 'Workshop Docs Agent' row")
                        page.wait_for_timeout(1500)
                        # how does a user start a chat from here? record candidate controls
                        n["chat_controls_seen"] = page.evaluate("""() => [...document.querySelectorAll('button,a,[role=button],[role=menuitem]')]
                            .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g,' '))
                            .filter(t => /chat|conversation|start|ask|open/i.test(t)).slice(0, 20)""")
                        c = click_first(page, [("chat button", page.get_by_role("button", name=re.compile(r"(chat|start|open|ask)", re.I))),
                                               ("chat link", page.get_by_role("link", name=re.compile(r"(chat|start|open|ask)", re.I)))], timeout=3000)
                        if c:
                            path.append(f"click '{c}'")
                        state["found"] = True
                n["url_path_now"] = page.url.replace(KB, "")
                if not state["found"]:
                    n["_status"] = "FAIL-agent-not-found"
                return n

            fa = run_step(page, "find-workshop-docs-agent", find_agent)

            def ask_agent():
                n = {"url_path_before_send": page.url.replace(KB, "")}
                box = None
                for label, loc in (("textarea", page.locator("textarea:visible")),
                                   ("contenteditable", page.locator('[contenteditable="true"]:visible')),
                                   ("textbox role", page.get_by_role("textbox"))):
                    if loc.count():
                        box, n["input_kind"] = loc.last, label
                        break
                if box is None:
                    n["_status"] = "FAIL-no-chat-input"
                    return n
                try:
                    n["header_agent_name_text"] = page.get_by_text(re.compile(r"Workshop Docs Agent", re.I)).count() > 0
                except Exception:  # noqa: BLE001
                    pass
                before = ""
                try:
                    before = page.inner_text("body", timeout=4000)
                except Exception:  # noqa: BLE001
                    pass
                box.click()
                try:
                    box.fill(QUESTION)
                except Exception:  # noqa: BLE001
                    page.keyboard.insert_text(QUESTION)
                shot(page, "agent-question-typed")
                sent = click_first(page, [("send button", page.locator('[data-test-subj*="submit" i]:visible, [data-test-subj*="send" i]:visible')),
                                          ("button Send/Submit", page.get_by_role("button", name=re.compile(r"^(send|submit)", re.I)))], timeout=2500)
                if not sent:
                    page.keyboard.press("Enter")
                    sent = "Enter key"
                n["sent_via"] = sent
                t0 = time.time()
                last_len, stable, grew, txt = -1, 0, False, before
                while time.time() - t0 < args.wait:
                    page.wait_for_timeout(3000)
                    try:
                        txt = page.inner_text("body", timeout=4000)
                    except Exception:  # noqa: BLE001
                        continue
                    grew = grew or len(txt) > len(before) + 200
                    stable = stable + 1 if len(txt) == last_len else 0
                    last_len = len(txt)
                    if grew and stable >= 4 and ("137" in txt or "memory" in txt.lower()):
                        break
                n["waited_s"] = round(time.time() - t0)
                n["url_path_after_send"] = page.url.replace(KB, "")
                new = txt.replace(before, "") if before and before in txt else txt
                n["response_grew_page"] = grew
                n["response_text_head"] = re.sub(r"\s+", " ", new)[:900]
                n["mentions_137_or_memory"] = ("137" in new) or ("memory" in new.lower())
                n["tool_call_evidence_in_text"] = sorted(set(m.lower() for m in re.findall(r"(search-workshop-docs-hybrid|load_skill|tool call|called tool|reasoning|thinking|searched|skill)", new, re.I)))
                if not grew:
                    n["_status"] = "FAIL-no-response"
                return n

            if fa["status"] == "ok":
                run_step(page, "agent-ask-and-wait", ask_agent)

                def expand_steps():
                    clicked = []
                    for pat in (r"(thinking|reasoning)", r"(show|view).*(steps|details|thinking|reasoning)", r"(tool|called|search|skill)", r"(steps|details)"):
                        try:
                            loc = page.get_by_role("button", name=re.compile(pat, re.I))
                            for i in range(min(loc.count(), 4)):
                                if loc.nth(i).is_visible():
                                    loc.nth(i).click(timeout=1500)
                                    clicked.append(pat)
                                    page.wait_for_timeout(600)
                        except Exception:  # noqa: BLE001
                            continue
                    shot(page, "agent-final-fullpage", full=True)
                    return {"expanded_controls": clicked, "url_path": page.url.replace(KB, "")}

                run_step(page, "agent-tool-call-display", expand_steps)
            else:
                LOG["steps"].append({"step": "agent-ask-and-wait", "status": "skipped", "notes": {"reason": "agent not found/opened"}})

        LOG["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_log()
        browser.close()

    bad = [s for s in LOG["steps"] if s["status"] not in ("ok", "skipped")]
    print(f"\n04_ui_playwright: {len(LOG['steps'])} steps, {len(bad)} not-ok. Log: {UI / 'ui_log.json'}")
    for s in bad:
        print(f"   - {s['step']}: {s['status']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
