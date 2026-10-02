#!/usr/bin/env python3
"""Parametrized ES|QL assertions for the ES|QL vector/keyword/hybrid workshop.

Every assertion = name, ES|QL (as the assignment.md / notebook shows it, ?q substituted the way the lab
tells the learner), expected outcome, and a CITATION (file:line, resolved at runtime by searching the doc
for a snippet, so the line number is always the one in the staged copy).

Levels
  EXACT    an exact rank / score recorded in TRAP_QUERY_VALIDATION_ESQL.md (or HANDOFF-ESQL.md)
  CLAIM    a teaching claim stated in TRAP/HANDOFF/README ("RRF #1 on all traps", "RERANK does not reorder" ...)
  LABTEXT  a statement made to the learner in assignment.md / notebook narrative (can contradict the golden doc)
  DERIVED  inferred by this harness (reported, but never affects the exit code)
  INFO     observation only, no verdict

Exit code is 1 if any EXACT/CLAIM/LABTEXT assertion FAILs or ERRORs.
Also runs EVERY ```esql block in every assignment.md verbatim (plus the "swap X for Y" variants the labs
describe) and every full-query ```esql block in the notebooks' markdown cells.

Reads only ES_ENDPOINT / ES_API_KEY (and ES_KIBANA_URL for the env check). Output: out/claims.md, out/claims_raw.json
"""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import common  # noqa: E402
from common import esql, lit, INDEX  # noqa: E402

common.require_env(("ES_ENDPOINT", "ES_API_KEY"))
common.stage_sources()

W = common.WORK
TRAP = W / "docs-esql" / "TRAP_QUERY_VALIDATION_ESQL.md"
HAND = W / "docs-esql" / "HANDOFF-ESQL.md"
README = W / "docs-esql" / "README-ESQL.md"
ASG = {n: W / "assignments" / d / "assignment.md" for n, d in zip(range(1, 6), common.LAB_DIRS)}
NB = {n: W / "notebooks-esql" / f for n, f in zip(range(1, 6), common.NOTEBOOKS)}
DOCS = {d["id"]: d for d in json.load(open(W / "corpus" / "docs.json"))}

V3 = ".jina-reranker-v3"
V2 = ".jina-reranker-v2-base-multilingual"
COMPLETION_ID = ".anthropic-claude-4.5-haiku-completion"
ILM_Q = common.LAB4_RAG_QUESTION
NOT_ENOUGH = re.compile(r"(do not|don't|do n't|cannot|can't) (have|find) (enough|sufficient)|not enough information|insufficient information", re.I)


def cite(path: Path, snippet: str) -> str:
    ln = common.find_line(path, snippet)
    nm = f"{path.parent.name}/{path.name}" if path.name == "assignment.md" else path.name
    return f"{nm}:{ln}" if ln else f"{path.name}:?(snippet not found: {snippet[:40]!r})"


# ---------------------------------------------------------------------------
# recorder
# ---------------------------------------------------------------------------
class Rec:
    def __init__(self):
        self.rows = []
        self.blocks = []

    def check(self, level, name, expected, ok, actual, cite_, *results, allow_status=False):
        results = [r for r in results if r is not None]
        bad = [r for r in results if not r.ok]
        if bad and not allow_status:
            r = bad[0]
            status = "ERROR"
            actual = f"HTTP {r.status}: {r.error[:200]}"
        elif ok is None:
            status = "INFO"
        else:
            status = "PASS" if ok else "FAIL"
        detail = []
        if status in ("FAIL", "ERROR"):
            for r in results:
                detail.append({"top5": r.top(5) if r.ok else f"HTTP {r.status}: {r.error[:200]}",
                               "query": getattr(r, "query", "")})
        self.rows.append({"n": len(self.rows) + 1, "level": level, "name": name, "expected": expected,
                          "actual": actual, "status": status, "cite": cite_, "detail": detail})
        mark = {"PASS": "ok  ", "FAIL": "FAIL", "ERROR": "ERR ", "INFO": "info"}[status]
        print(f"  [{mark}] {level:<7} {name}  ->  {actual[:110]}", flush=True)
        return status == "PASS"


R = Rec()


def section(t):
    print(f"\n## {t}", flush=True)


# ---------------------------------------------------------------------------
# query builders -- same shapes as assignment.md / TRAP templates (literal query strings)
# ---------------------------------------------------------------------------
def q_sem(q, limit=10):
    return (f"FROM {INDEX} METADATA _score\n| WHERE MATCH(body_semantic, {lit(q)})\n"
            f"| SORT _score DESC | LIMIT {limit} | KEEP id, title, summary, _score")


def q_bm25(q, limit=10):
    return (f"FROM {INDEX} METADATA _score\n"
            f'| WHERE MATCH(title, {lit(q)}, {{"boost": 3.0}}) OR MATCH(body, {lit(q)})\n'
            f"| SORT _score DESC | LIMIT {limit} | KEEP id, title, summary, _score")


def q_rrf(q, limit=10, keep="id, title, summary, _score"):
    return (f"FROM {INDEX} METADATA _score, _id, _index\n"
            f"| FORK ( WHERE MATCH(body, {lit(q)})          | SORT _score DESC | LIMIT 50 )\n"
            f"       ( WHERE MATCH(body_semantic, {lit(q)}) | SORT _score DESC | LIMIT 50 )\n"
            f"| FUSE | SORT _score DESC | LIMIT {limit} | KEEP {keep}")


def q_linear(q, w1, w2, limit=5):
    return (f"FROM {INDEX} METADATA _score, _id, _index\n"
            f"| FORK ( WHERE MATCH(body, {lit(q)})          | SORT _score DESC | LIMIT 50 )\n"
            f"       ( WHERE MATCH(body_semantic, {lit(q)}) | SORT _score DESC | LIMIT 50 )\n"
            f'| FUSE LINEAR WITH {{"weights": {{"fork1": {w1}, "fork2": {w2}}}, "normalizer": "minmax"}}\n'
            f"| SORT _score DESC | LIMIT {limit} | KEEP id, title, summary, _score")


def q_rerank(q, inf_id, cand=8, limit=8, sort_after=True):
    tail = "| SORT _score DESC " if sort_after else ""
    return (f"FROM {INDEX} METADATA _score, _id, _index\n"
            f"| FORK ( WHERE MATCH(body, {lit(q)})          | SORT _score DESC | LIMIT 50 )\n"
            f"       ( WHERE MATCH(body_semantic, {lit(q)}) | SORT _score DESC | LIMIT 50 )\n"
            f"| FUSE | SORT _score DESC | LIMIT {cand}\n"
            f'| RERANK {lit(q)} ON body WITH {{"inference_id": "{inf_id}"}}\n'
            f"{tail}| LIMIT {limit} | KEEP id, title, summary, _score")


def rank_of(res, doc):
    return res.rank(doc) if res.ok else None


# ===========================================================================
# 0. connectivity / auth gate
# ===========================================================================
section("0. connectivity")
probe = esql(f"FROM {INDEX} | STATS docs = COUNT(*)")
if probe.status in (401, 403) or probe.status == 0:
    print(f"\nABORT: cannot query the cluster (HTTP {probe.status}: {probe.error}). "
          "Check ES_ENDPOINT / ES_API_KEY.")
    sys.exit(2)

# ===========================================================================
# 1. LAB 1
# ===========================================================================
section("Lab 1 - semantic search")
A1 = ASG[1]
r = esql(f"FROM {INDEX}\n| STATS docs = COUNT(*)")
R.check("EXACT", "L1 corpus count via STATS COUNT(*)", "62 docs",
        r.ok and r.rows and r.rows[0].get("docs") == 62, f"docs={r.rows[0].get('docs') if r.ok and r.rows else None}",
        f"{cite(A1, 'You should see **62**')}; {cite(TRAP, '62 docs')}", r)

WOW = [("securing cluster traffic", "doc-010"), ("how do I back up my cluster data", "doc-037"),
       ("users can't connect to Kibana", "doc-024")]
for q, tgt in WOW:
    r = esql(q_sem(q, 5))
    R.check("EXACT", f"L1 semantic #1 [{q}]", f"{tgt} at rank 1", r.ok and r.rank(tgt) == 1,
            f"{tgt} at rank {(r.rank(tgt) or 'absent from top 5') if r.ok else '?'}", cite(TRAP, f"| `{q}` | {tgt}"), r)
r = esql(q_sem("securing cluster traffic", 5))
R.check("DERIVED", "L1 results include _score column, sorted DESC",
        "columns id,title,summary,_score; scores non-increasing",
        r.ok and r.names == ["id", "title", "summary", "_score"] and r.scores() == sorted(r.scores(), reverse=True),
        f"columns={r.names if r.ok else '?'}", cite(A1, "The `_score` column appears whenever"), r)
r = esql(f'FROM {INDEX}\n| WHERE MATCH(body_semantic, "securing cluster traffic")\n| LIMIT 5 | KEEP id, _score')
R.check("DERIVED", "L1 omitting METADATA _score then KEEP _score is an error (learner mistake mode)",
        "HTTP 400 (unknown column _score)", r.status == 400, f"HTTP {r.status}: {r.error[:100]}",
        cite(A1, "Without `METADATA _score`"), allow_status=True, *[r])
t = DOCS["doc-010"]["title"] + " " + DOCS["doc-010"]["body"]
R.check("LABTEXT", "L1 corpus fact: doc-010 is a TLS doc (title says TLS)",
        "'TLS' in doc-010 title", "tls" in DOCS["doc-010"]["title"].lower(), DOCS["doc-010"]["title"],
        cite(A1, "TLS / cluster-communications page"))

# ===========================================================================
# 2. LAB 2 + trap table
# ===========================================================================
section("Lab 2 / trap table - semantic vs BM25 vs RRF ranks")
TRAPS = [  # query, target, semantic, bm25, rrf
    ("exit code 137", "doc-007", 1, 2, 1),
    ("new_primaries", "doc-008", 2, 1, 1),
    ("cluster.routing.allocation.enable", "doc-008", 1, 2, 1),
    ("8.18 breaking changes", "doc-057", 1, 2, 1),
    ("notify me when something goes wrong", "doc-049", 1, 5, 1),
    ("reduce storage cost for old logs", "doc-041", 1, 5, 1),
]
TR = {}
for q, tgt, es_, eb, er in TRAPS:
    c = cite(TRAP, f"| `{q}` | {tgt}")
    TR[q] = (esql(q_sem(q)), esql(q_bm25(q)), esql(q_rrf(q)))
    for label, res, exp in zip(("semantic", "BM25", "RRF"), TR[q], (es_, eb, er)):
        got = rank_of(res, tgt)
        R.check("EXACT", f"TRAP [{q}] {label} rank of {tgt}", f"rank {exp}", got == exp,
                f"rank {got if got else '>10/absent'}", c, res)
R.check("CLAIM", "TRAP RRF lands the target at #1 on ALL six trap queries", "6/6 rank 1",
        all(rank_of(TR[q][2], t) == 1 for q, t, *_ in TRAPS),
        ", ".join(f"{t}:{rank_of(TR[q][2], t)}" for q, t, *_ in TRAPS),
        cite(TRAP, "**RRF lands the target at #1 on every single trap query.**"), *[TR[q][2] for q, *_ in TRAPS])

A2 = ASG[2]
# -- Failure 1 ---------------------------------------------------------------
s137, b137, _ = TR["exit code 137"]
R.check("CLAIM", "TRAP BM25 #1 for [exit code 137] is the boosted-title distractor doc-061 (not doc-007)",
        "BM25 top row id == doc-061", b137.ok and b137.ids[:1] == ["doc-061"],
        f"BM25 top-1 = {b137.ids[:1]}", f"{cite(TRAP, '(a boosted-title distractor, `doc-061`')}; {cite(HAND, 'sends a boosted-title distractor')}", b137)
R.check("LABTEXT", "CONFLICT CHECK: Lab 2 page says BM25 [exit code 137] makes doc-007 'win decisively' (#1)",
        "doc-007 BM25 rank 1 (as the lab page tells the learner)", b137.ok and b137.rank("doc-007") == 1,
        f"doc-007 BM25 rank {b137.rank('doc-007') if b137.ok else '?'}; BM25 top-5: {b137.top(5)}",
        f"{cite(A2, 'watch `doc-007` win decisively')} vs {cite(TRAP, '| `exit code 137` | doc-007')}", b137)
R.check("LABTEXT", "CONFLICT CHECK: Lab 2 notebook cell 5 says BM25 'wins decisively' on [exit code 137]",
        "doc-007 BM25 rank 1", b137.ok and b137.rank("doc-007") == 1,
        f"doc-007 BM25 rank {b137.rank('doc-007') if b137.ok else '?'}",
        "lab2-esql-where-vector-breaks.ipynb cell 5 + cell 19 table", b137)
if s137.ok and len(s137.rows) >= 2:
    sc = s137.scores()
    gap = (sc[0] - sc[1]) / sc[0] if sc[0] else None
    near = [(r_["id"], "137" in (DOCS.get(r_["id"], {}).get("body", "") + DOCS.get(r_["id"], {}).get("title", "")))
            for r_ in s137.rows[:4]]
    R.check("INFO", "L2 semantic [exit code 137]: margin of #1 over #2 ('by a hair') and which neighbours contain '137'",
            "small relative margin; distractors lack '137'", None,
            f"#1={s137.ids[0]} rel.gap to #2={gap:.3f}; top-4 contains-137: {near}",
            cite(A2, "may still be #1"), s137)
HAS137 = sorted(d for d, x in DOCS.items() if re.search(r"\b137\b", x["title"] + " " + x["body"]))
R.check("LABTEXT", "L2 corpus fact: only doc-007 contains the token '137' in body/title (notebook cell 5: 'appears in exactly one doc')",
        "exactly {doc-007}", HAS137 == ["doc-007"], f"docs containing 137: {HAS137}",
        "lab2 notebook cell 5; " + cite(A2, "distractor docs that never say"))
s8, b8, _ = TR["new_primaries"]
R.check("LABTEXT", "L2 [new_primaries]: semantic lands a plausible WRONG doc at #1; BM25 pins doc-008",
        "semantic #1 != doc-008; BM25 #1 == doc-008",
        s8.ok and b8.ok and s8.ids[:1] != ["doc-008"] and b8.ids[:1] == ["doc-008"],
        f"semantic top-1={s8.ids[:1]} BM25 top-1={b8.ids[:1]}",
        f"{cite(A2, 'Try `new_primaries`')}; {cite(TRAP, 'semantic wrong doc at #2')} (AMBIGUOUS wording)", s8, b8)
# -- Failure 2 ---------------------------------------------------------------
s18, b18, _ = TR["8.18 breaking changes"]
R.check("LABTEXT", "L2 [8.18 breaking changes]: BM25 ranks doc-006 #1 (wrong); semantic gets doc-057 right",
        "BM25 #1 == doc-006; semantic #1 == doc-057", b18.ids[:1] == ["doc-006"] and s18.ids[:1] == ["doc-057"],
        f"BM25 top-1={b18.ids[:1]}; semantic top-1={s18.ids[:1]}",
        f"{cite(A2, 'BM25 ranks `doc-006`')}; {cite(TRAP, '(`doc-006` boosted title)')}", b18, s18)
for lab, qq, field_q in (("title-only", 'WHERE MATCH(title, "8.18 breaking changes", {"boost": 3.0})', "doc-006"),
                         ("body-only", 'WHERE MATCH(body, "8.18 breaking changes")', "doc-057")):
    rr = esql(f"FROM {INDEX} METADATA _score\n| {qq}\n| SORT _score DESC | LIMIT 5 | KEEP id, title, _score")
    R.check("EXACT", f"L2 explain-gap {lab} #1 for [8.18 breaking changes]", f"{field_q} at rank 1",
            rr.ok and rr.ids[:1] == [field_q], f"top-1={rr.ids[:1]}",
            cite(TRAP, "| title-only" if lab == "title-only" else "| body-only"), rr)
    if lab == "title-only":
        t_only = rr
    else:
        b_only = rr
# derived: ES|QL sums the two clauses (HANDOFF quirk 1)
if t_only.ok and b_only.ok and b18.ok:
    ts = {r_["id"]: r_["_score"] for r_ in t_only.rows}
    bs = {r_["id"]: r_["_score"] for r_ in b_only.rows}
    cs = {r_["id"]: r_["_score"] for r_ in esql(q_bm25("8.18 breaking changes", 5)).rows}
    d006 = (ts.get("doc-006", 0) + bs.get("doc-006", 0), cs.get("doc-006"))
    R.check("DERIVED", "L2 quirk: combined BM25 score == title-only + body-only (SUM, not max) for doc-006",
            "|sum - combined| / combined < 2%", d006[1] is not None and abs(d006[0] - d006[1]) / d006[1] < 0.02,
            f"title+body={d006[0]:.4f} combined={d006[1]}", cite(HAND, "ES|QL BM25 SUMS field scores"), t_only, b_only)
# SCORE(MATCH()) bonus
r = esql(f"""FROM {INDEX} METADATA _score
| WHERE MATCH(title, "8.18 breaking changes", {{"boost": 3.0}}) OR MATCH(body, "8.18 breaking changes")
| EVAL title_score = SCORE(MATCH(title, "8.18 breaking changes", {{"boost": 3.0}})),
       body_score  = SCORE(MATCH(body,  "8.18 breaking changes"))
| SORT _score DESC | LIMIT 5
| KEEP id, title, _score, title_score, body_score""")
R.check("CLAIM", "L2 SCORE(MATCH(...)) works and yields per-field score columns",
        "HTTP 200; columns title_score, body_score", r.ok and {"title_score", "body_score"} <= set(r.names),
        f"HTTP {r.status}; columns={r.names}", f"{cite(TRAP, '`SCORE(MATCH(...))`~~')}; {cite(HAND, '**`SCORE(MATCH(...))` works**')}", r)
if r.ok and r.rows:
    top = r.rows[0]
    R.check("DERIVED", "L2 SCORE(): top row (doc-006) is title-driven (title_score > body_score)",
            "title_score > body_score for the #1 row", (top.get("title_score") or 0) > (top.get("body_score") or 0),
            f"{top.get('id')}: title_score={top.get('title_score')} body_score={top.get('body_score')}",
            cite(A2, "Title-only** rewards"), r)
r = esql(f"""FROM {INDEX} METADATA _score
| WHERE MATCH(title, "8.18 breaking changes", {{"boost": 3.0}}) OR MATCH(body, "8.18 breaking changes")
| EVAL s = SCORE()
| LIMIT 5 | KEEP id, s""")
R.check("CLAIM", "Quirk: zero-arg SCORE() still errors", "HTTP 400", r.status == 400, f"HTTP {r.status}: {r.error[:90]}",
        cite(HAND, "Zero-arg `SCORE()` still errors"), r, allow_status=True)
for label, qq in (("MATCH(\"title,body\", q)", f'FROM {INDEX} METADATA _score | WHERE MATCH("title,body", "x") | LIMIT 1'),
                  ("MULTI_MATCH", f'FROM {INDEX} METADATA _score | WHERE MULTI_MATCH("x", title, body) | LIMIT 1')):
    r = esql(qq)
    R.check("CLAIM", f"Quirk: multi-field {label} rejected", "HTTP 400", r.status == 400, f"HTTP {r.status}: {r.error[:90]}",
            cite(HAND, "**No multi-field MATCH**"), r, allow_status=True)
# -- Failure 3 ---------------------------------------------------------------
sn, bn, _ = TR["notify me when something goes wrong"]
R.check("LABTEXT", "L2 [notify me...]: semantic finds doc-049 #1; BM25 buries it (rank 5)",
        "semantic rank 1; BM25 rank 5", sn.rank("doc-049") == 1 and bn.rank("doc-049") == 5,
        f"semantic rank {sn.rank('doc-049')}; BM25 rank {bn.rank('doc-049')}", f"{cite(A2, 'BM25 **buries** it')}; {cite(TRAP, '| `notify me when something goes wrong` | doc-049')}", sn, bn)
b049 = DOCS["doc-049"]["body"].lower()
R.check("LABTEXT", "L2 corpus fact: doc-049 body contains no 'notify', 'something' or 'goes wrong' but does say trigger/condition/webhook",
        "no overlap words; has trigger+condition+webhook",
        not any(w in b049 for w in ("notify", "something", "goes wrong")) and all(w in b049 for w in ("trigger", "condition", "webhook")),
        f"notify:{'notify' in b049} something:{'something' in b049} goes wrong:{'goes wrong' in b049} trigger:{'trigger' in b049} condition:{'condition' in b049} webhook:{'webhook' in b049}",
        cite(A2, "never \"notify\""))
for d, frag in (("doc-006", "Elasticsearch breaking changes"), ("doc-057", "8.18 release notes"), ("doc-058", "8.15 release notes")):
    R.check("LABTEXT", f"L2 corpus fact: {d} title is '{frag}'", frag, frag.lower() in DOCS[d]["title"].lower(), DOCS[d]["title"],
            "lab2 notebook cell 9")
# ===========================================================================
# 3. LAB 3
# ===========================================================================
section("Lab 3 - RRF, linear, filter, rerank preview")
A3 = ASG[3]
for q, tgt in (("notify me when something goes wrong", "doc-049"), ("8.18 breaking changes", "doc-057"),
               ("new_primaries", "doc-008"), ("exit code 137", "doc-007")):
    r = esql(q_rrf(q, 5))
    R.check("LABTEXT", f"L3 Part A RRF [{q}] -> {tgt} #1 (assignment LIMIT 5)", f"{tgt} rank 1", r.ids[:1] == [tgt],
            f"top-1={r.ids[:1]}", cite(A3, "RRF lands the target at #1 on all four"), r)
# literal vs ?q parameter equivalence (TRAP:158 / notebook passes ?q as named param)
tmpl = (f"FROM {INDEX} METADATA _score, _id, _index\n| FORK ( WHERE MATCH(body, ?q) | SORT _score DESC | LIMIT 50 )\n"
        f"       ( WHERE MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )\n| FUSE | SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score")
rp = esql(tmpl, [{"q": "notify me when something goes wrong"}])
rl = esql(q_rrf("notify me when something goes wrong", 5))
R.check("DERIVED", "L3 named-param (?q via params=[{q:..}]) returns same ids as the literal-string query",
        "identical id order", rp.ok and rl.ok and rp.ids == rl.ids, f"param={rp.ids} literal={rl.ids}",
        cite(TRAP, "`es.esql.query` named-param format"), rp, rl)
# ES|QL FUSE vs _search rrf retriever (notebook cell 0 claim)
try:
    import requests
    same = []
    for q, tgt, *_ in TRAPS:
        body = {"size": 5, "_source": ["id"], "retriever": {"rrf": {"retrievers": [
            {"standard": {"query": {"match": {"body": q}}}},
            {"standard": {"query": {"semantic": {"field": "body_semantic", "query": q}}}}],
            "rank_window_size": 50, "rank_constant": 60}}}
        rr = requests.post(f"{os.environ['ES_ENDPOINT']}/{INDEX}/_search", headers=common._headers(), json=body, timeout=120)
        ids = [h["_source"]["id"] for h in rr.json().get("hits", {}).get("hits", [])] if rr.status_code == 200 else None
        same.append((q, ids[:1] if ids else None, TR[q][2].ids[:1]))
    R.check("DERIVED", "L3 FORK|FUSE top-1 equals _search rrf-retriever top-1 on all 6 traps (notebook cell 0: 'same ranking')",
            "top-1 identical", all(a == b for _, a, b in same), "; ".join(f"{q[:18]}: dsl={a} esql={b}" for q, a, b in same),
            "lab3 notebook cell 0; setup_agent.py HYBRID_ESQL comment")
except Exception as e:  # noqa: BLE001
    R.check("INFO", "L3 _search rrf comparison", "-", None, f"skipped: {type(e).__name__}: {e}", "-")

# Part B linear
LIN_Q = "notify me when something goes wrong"
for (w1, w2, exp_rank, exp_top1, tag) in ((0.8, 0.2, 4, "doc-061", "BM25-lean"), (0.5, 0.5, 2, "doc-061", "balanced"),
                                          (0.3, 0.7, 1, "doc-049", "semantic-lean")):
    r = esql(q_linear(LIN_Q, w1, w2))
    c = cite(TRAP, f"| {tag}")
    R.check("EXACT", f"L3 Part B FUSE LINEAR {w1}/{w2} ({tag}): doc-049 rank", f"doc-049 rank {exp_rank}", r.rank("doc-049") == exp_rank,
            f"doc-049 rank {r.rank('doc-049')}", c, r)
    R.check("EXACT", f"L3 Part B FUSE LINEAR {w1}/{w2} ({tag}): #1 doc", f"{exp_top1} at #1", r.ids[:1] == [exp_top1],
            f"top-1={r.ids[:1]}", c, r)
    R.check("CLAIM", f"Quirk: FUSE LINEAR {w1}/{w2} renormalises so fused #1 score == 1.0", "top _score == 1.0 (+-0.001)",
            r.ok and r.rows and abs(r.rows[0]["_score"] - 1.0) < 1e-3, f"top _score={r.rows[0]['_score'] if r.ok and r.rows else None}",
            cite(HAND, "renormalizes so fused #1 always = 1.0"), r)
r = esql(q_linear(LIN_Q, 0.8, 0.2))
R.check("LABTEXT", "L3 Part B: 0.8 BM25 'sinks it out of the top few' (doc-049 below #1; docs say rank 4 - 'top few' is vague)",
        "doc-049 rank > 1", (r.rank("doc-049") or 99) > 1, f"doc-049 rank {r.rank('doc-049')}", cite(A3, "sinks it out of the top few"), r)
for w1, w2 in ((0.8, 0.2), (0.5, 0.5), (0.2, 0.8)):
    r = esql(q_linear("8.18 breaking changes", w1, w2))
    R.check("CLAIM", f"TRAP linear [8.18 breaking changes] {w1}/{w2}: doc-057 wins outright (backfire does NOT reproduce)",
            "doc-057 #1", r.ids[:1] == ["doc-057"], f"top-1={r.ids[:1]}", cite(TRAP, "wins outright at every weight tested"), r)
r = esql(q_linear(LIN_Q, 0.0, 1.0))
R.check("CLAIM", "Quirk: FUSE LINEAR weight 0.0 rejected ('expected weight to be positive')",
        "HTTP 400 mentioning 'positive'", r.status == 400 and "positive" in r.error.lower(), f"HTTP {r.status}: {r.error[:100]}",
        cite(TRAP, "weights must be **positive**"), r, allow_status=True)

# MRR sweep (mirrors notebook cell 6/12/14: LIMIT 60 templates with ?q, linear LIMIT 5)
JUDG = [("exit code 137", "doc-007"), ("new_primaries", "doc-008"), ("8.18 breaking changes", "doc-057"),
        ("notify me when something goes wrong", "doc-049")]
NBQ = {
    "sem": f"FROM {INDEX} METADATA _score\n| WHERE MATCH(body_semantic, ?q)\n| SORT _score DESC | LIMIT 60 | KEEP id, title, summary, _score",
    "bm25": f'FROM {INDEX} METADATA _score\n| WHERE MATCH(title, ?q, {{"boost": 3.0}}) OR MATCH(body, ?q)\n| SORT _score DESC | LIMIT 60 | KEEP id, title, summary, _score',
    "rrf": (f"FROM {INDEX} METADATA _score, _id, _index\n| FORK ( WHERE MATCH(body, ?q)          | SORT _score DESC | LIMIT 50 )\n"
            f"       ( WHERE MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )\n| FUSE\n| SORT _score DESC | LIMIT 60 | KEEP id, title, summary, _score"),
}


def nb_linear(w1, w2):
    return (f"FROM {INDEX} METADATA _score, _id, _index\n| FORK ( WHERE MATCH(body, ?q)          | SORT _score DESC | LIMIT 50 )\n"
            f"       ( WHERE MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )\n"
            f'| FUSE LINEAR WITH {{"weights": {{"fork1": {w1}, "fork2": {w2}}}, "normalizer": "minmax"}}\n'
            f"| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score")


def nb_ranks(tmpl):
    out, rs = [], []
    for q, g in JUDG:
        rr = esql(tmpl, [{"q": q}])
        rs.append(rr)
        out.append(rr.rank(g))
    return out, rs


def mrr(ranks):
    return sum((1.0 / r) if r else 0.0 for r in ranks) / len(ranks)


rk = {}
rk["BM25"], rs_b = nb_ranks(NBQ["bm25"])
rk["Semantic"], rs_s = nb_ranks(NBQ["sem"])
rk["RRF"], rs_r = nb_ranks(NBQ["rrf"])
sweep = []
for i in range(1, 10):
    ws = round(i * 0.1, 1)
    wb = round(1.0 - ws, 1)
    rks, _ = nb_ranks(nb_linear(wb, ws))
    sweep.append((wb, ws, mrr(rks), rks))
best = max(sweep, key=lambda x: x[2])
R.check("DERIVED", "L3 MRR(BM25) from TRAP ranks 2,1,2,5", "0.550", abs(mrr(rk["BM25"]) - 0.55) < 1e-3, f"ranks={rk['BM25']} MRR={mrr(rk['BM25']):.3f}",
        cite(TRAP, "| `exit code 137` | doc-007") + " (+ rows for new_primaries, 8.18, notify)", *rs_b)
R.check("DERIVED", "L3 MRR(Semantic) from TRAP ranks 1,2,1,1", "0.875", abs(mrr(rk["Semantic"]) - 0.875) < 1e-3, f"ranks={rk['Semantic']} MRR={mrr(rk['Semantic']):.3f}",
        cite(TRAP, "| `exit code 137` | doc-007") + " (+ rows)", *rs_s)
R.check("CLAIM", "L3 MRR(RRF, no tuning) == 1.000", "1.000", abs(mrr(rk["RRF"]) - 1.0) < 1e-6, f"ranks={rk['RRF']} MRR={mrr(rk['RRF']):.3f}",
        cite(TRAP, "**RRF lands the target at #1"), *rs_r)
R.check("INFO", "L3 linear weight sweep (BM25/semantic -> MRR)", "see detail", None,
        "; ".join(f"{a}/{b}->{c:.3f}" for a, b, c, _ in sweep), "lab3 notebook cell 12")
R.check("LABTEXT", "L3 notebook cell 12: best measured linear split leans semantic (w_sem > w_bm25)", "best w_sem > 0.5",
        best[1] > best[0], f"best BM25={best[0]} / sem={best[1]} MRR={best[2]:.3f}", "lab3 notebook cell 12 closing prints")
R.check("LABTEXT", "L3 notebook cell 12: RRF (zero tuning) matches/beats the best linear MRR", "MRR(RRF) >= best linear",
        mrr(rk["RRF"]) + 1e-9 >= best[2], f"RRF={mrr(rk['RRF']):.3f} bestLinear={best[2]:.3f}", "lab3 notebook cell 12 closing prints")
heat = {"BM25": rk["BM25"], "Semantic": rk["Semantic"], "RRF hybrid": rk["RRF"]}
for w1, w2 in ((0.8, 0.2), (0.5, 0.5), (0.2, 0.8)):
    heat[f"Linear {w1}/{w2}"] = nb_ranks(nb_linear(w1, w2))[0]
R.check("LABTEXT", "L3 heatmap cell 14: RRF row all rank 1; every other row has >=1 non-1 cell",
        "RRF all 1; others each have a non-1", all(x == 1 for x in heat["RRF hybrid"]) and all(any(x != 1 for x in v) for k, v in heat.items() if k != "RRF hybrid"),
        "; ".join(f"{k}={v}" for k, v in heat.items()), "lab3 notebook cell 14 closing print")

# Part C filter
r = esql(f"""FROM {INDEX} METADATA _score, _id, _index
| FORK ( WHERE version_tags == "8.18" AND MATCH(body, "breaking changes")          | SORT _score DESC | LIMIT 50 )
       ( WHERE version_tags == "8.18" AND MATCH(body_semantic, "breaking changes") | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score, version_tags""")
eligible = {d for d, x in DOCS.items() if "8.18" in (x.get("version_tags") or [])}
tagsok = r.ok and all("8.18" in (v if isinstance(v, list) else [v]) for v in [row.get("version_tags") for row in r.rows])
R.check("CLAIM", "L3 Part C FORK-branch filter: only 8.18-tagged docs returned; doc-006 filtered out",
        f"ids subset of {sorted(eligible)}; doc-006 absent", r.ok and set(r.ids) <= eligible and "doc-006" not in r.ids and tagsok,
        f"ids={r.ids}", cite(A3, "Only `8.18`-tagged docs are eligible"), r)
R.check("INFO", "L3 Part C: rows returned by the filtered query (only docs tagged 8.18 are eligible, per docs.json)",
        "n/a", None, f"{len(r.ids) if r.ok else '?'} row(s); eligible per corpus: {sorted(eligible)} -> a LIMIT 5 query can show at most {len(eligible)} row(s)",
        cite(A3, "Only `8.18`-tagged docs are eligible"), r)
rfree = esql(q_rrf("breaking changes", 5))
R.check("DERIVED", "L3 Part C contrast: unfiltered RRF [breaking changes] includes doc-006 in top 5 (so the filter has an effect)",
        "doc-006 in top 5 unfiltered", rfree.ok and "doc-006" in rfree.ids, f"unfiltered ids={rfree.ids}", cite(A3, "boosted-title distractor is filtered"), rfree)
# FORK filter on trap_type (used by lab 4 BAD context): results restricted to the tagged docs
vs = {d for d, x in DOCS.items() if x.get("trap_type") == "version-specific"}
r = esql(f"""FROM {INDEX} METADATA _score, _id, _index
| FORK ( WHERE trap_type == "version-specific" AND MATCH(body, {lit(ILM_Q)})          | SORT _score DESC | LIMIT 50 )
       ( WHERE trap_type == "version-specific" AND MATCH(body_semantic, {lit(ILM_Q)}) | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 10 | KEEP id, title, _score""")
R.check("CLAIM", "FORK-branch filter restricts results: trap_type=='version-specific' returns only those docs",
        f"ids subset of {sorted(vs)}", r.ok and set(r.ids) <= vs, f"ids={r.ids}", "lab4 notebook cell 6/7", r)
# Rerank preview in Lab 3
r3 = esql(f"""FROM {INDEX} METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, "reduce storage cost for old logs")          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, "reduce storage cost for old logs") | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 20
| RERANK "reduce storage cost for old logs" ON body WITH {{"inference_id": "{V3}"}}
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score""")
R.check("EXACT", "L3 rerank preview (LIMIT 20 candidates) [reduce storage cost for old logs]: v3 flips to doc-017 #1", "doc-017 rank 1",
        r3.ids[:1] == ["doc-017"], f"top-1={r3.ids[:1]}", cite(TRAP, "**listwise (v3) flips to"), r3)

# ===========================================================================
# 4. LAB 4
# ===========================================================================
section("Lab 4 - one-query RAG (RERANK + COMPLETION), good vs bad context")
A4 = ASG[4]
Q_RET = (f"FROM {INDEX} METADATA _score, _id, _index\n| FORK ( WHERE MATCH(body, ?q)          | SORT _score DESC | LIMIT 50 )\n"
         f"       ( WHERE MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )\n| FUSE | SORT _score DESC | LIMIT 20\n"
         f'| RERANK ?q ON body WITH {{"inference_id": "{V3}"}}\n| SORT _score DESC | LIMIT 5 | KEEP id, title, _score')
r = esql(Q_RET, [{"q": ILM_Q}])
R.check("CLAIM", "L4 stage 1+2 (FORK|FUSE|RERANK via ?q params) for the ILM question: doc-017 #1", "doc-017 rank 1", r.ids[:1] == ["doc-017"],
        f"top5={r.top(5)}", cite(TRAP, "retrieves `doc-017` (ILM overview)"), r)
R.check("CLAIM", "Quirk: ?q named param works inside RERANK query-text position", "HTTP 200", r.ok, f"HTTP {r.status}", cite(TRAP, "named param inside"), r)

PIPE_TMPL = (f"FROM {INDEX} METADATA _score, _id, _index\n"
             "| FORK ( WHERE MATCH(body, ?q)          | SORT _score DESC | LIMIT 50 )\n"
             "       ( WHERE MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )\n"
             "| FUSE | SORT _score DESC | LIMIT 20\n"
             f'| RERANK ?q ON body WITH {{"inference_id": "{V3}"}}\n'
             "| SORT _score DESC | LIMIT 1\n"
             '| EVAL prompt = CONCAT("Answer the question using ONLY the document below. Title: ", title, " === Document: ", body, " === Question: ", ?q)\n'
             f'| COMPLETION answer = prompt WITH {{"inference_id": "{COMPLETION_ID}"}}\n'
             "| KEEP id, title, answer")
rp = esql(PIPE_TMPL, [{"q": ILM_Q}], timeout=300)
ans = rp.rows[0].get("answer") if rp.ok and rp.rows else None
R.check("CLAIM", "L4 headline one-query FORK|FUSE|RERANK|COMPLETION (?q params): non-empty answer from doc-017",
        "1 row; id doc-017; answer non-empty (>80 chars)", rp.ok and len(rp.rows) == 1 and rp.rows[0].get("id") == "doc-017" and bool(ans) and len(str(ans)) > 80,
        f"rows={len(rp.rows)} id={rp.rows[0].get('id') if rp.rows else None} answer_len={len(str(ans)) if ans else 0} elapsed={rp.elapsed:.1f}s",
        f"{cite(TRAP, '`COMPLETION` returns a non-empty `answer`')}; {cite(A4, '## The headline query')}", rp)
R.check("INFO", "L4 headline latency (docs: COMPLETION ~1.2-2.6s, RERANK ~0.3s; lab text: 'multi-second spinner')",
        "n/a", None, f"{rp.elapsed:.1f}s total", cite(TRAP, "latency ~1.2"), rp)
if ans:
    R.check("INFO", "L4 headline answer text (first 300 chars)", "n/a", None, str(ans)[:300].replace("\n", " "), "-", rp)

# the literal version the lab tells learners to paste into Discover (replace ?q in ALL places)
lit_pipe = PIPE_TMPL.replace("?q", lit(ILM_Q))
rl = esql(lit_pipe, timeout=300)
al = rl.rows[0].get("answer") if rl.ok and rl.rows else None
R.check("CLAIM", "L4 Discover peek (literal question substituted for every ?q): answer non-empty",
        "1 row; answer non-empty", rl.ok and len(rl.rows) == 1 and bool(al), f"rows={len(rl.rows)} answer_len={len(str(al)) if al else 0} elapsed={rl.elapsed:.1f}s",
        cite(TRAP, "Discover peek query (literal-string version)"), rl)
R.check("INFO", "L4 ?q occurrences in the headline query vs lab text 'replaced ... in all three places'",
        "3", None, f"{PIPE_TMPL.count('?q')} occurrences of ?q (FORK x2, RERANK, CONCAT) -> text says 'three places'",
        cite(A4, "in all three places"))


def run_rag(question, bad):
    filt = 'WHERE trap_type == "version-specific" AND ' if bad else "WHERE "
    q = (f"FROM {INDEX} METADATA _score, _id, _index\n"
         f"| FORK ( {filt}MATCH(body, ?q)          | SORT _score DESC | LIMIT 50 )\n"
         f"       ( {filt}MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )\n"
         "| FUSE | SORT _score DESC | LIMIT 1\n"
         '| EVAL prompt = CONCAT("Answer the question using ONLY the document below. '
         'If it lacks the answer, say you do not have enough information. '
         'Title: ", title, " === Document: ", body, " === Question: ", ?q)\n'
         f'| COMPLETION answer = prompt WITH {{"inference_id": "{COMPLETION_ID}"}}\n'
         "| KEEP id, title, answer")
    return esql(q, [{"q": question}], timeout=300)


good = run_rag(ILM_Q, False)
bad = run_rag(ILM_Q, True)
ga = str(good.rows[0].get("answer") or "") if good.ok and good.rows else ""
ba = str(bad.rows[0].get("answer") or "") if bad.ok and bad.rows else ""
R.check("EXACT", "L4 GOOD context retrieves doc-017 and answers", "id doc-017; answer non-empty and NOT 'not enough information'",
        good.ok and good.rows and good.rows[0]["id"] == "doc-017" and len(ga) > 80 and not NOT_ENOUGH.search(ga),
        f"id={good.rows[0]['id'] if good.ok and good.rows else None}; answer[:120]={ga[:120]!r}", cite(TRAP, "- [x] GOOD context"), good)
R.check("EXACT", "L4 BAD context (trap_type=version-specific) retrieves doc-056 and says 'not enough information'",
        "id doc-056; answer matches 'do not have enough information'", bad.ok and bad.rows and bad.rows[0]["id"] == "doc-056" and bool(NOT_ENOUGH.search(ba)),
        f"id={bad.rows[0]['id'] if bad.ok and bad.rows else None}; answer[:160]={ba[:160]!r}", cite(TRAP, "- [x] BAD context"), bad)
R.check("CLAIM", "L4 GOOD vs BAD answers differ in kind (the lab's headline contrast)", "good answer substantive, bad answer refuses",
        len(ga) > len(ba) and bool(NOT_ENOUGH.search(ba)) and not NOT_ENOUGH.search(ga), f"len good={len(ga)} bad={len(ba)}",
        "lab4 notebook cells 7-9", good, bad)
# regression guard for the swapped-out SAML question
old_q = "How do I configure SAML authentication in Elasticsearch?"
old = run_rag(old_q, False)
oa = str(old.rows[0].get("answer") or "") if old.ok and old.rows else ""
R.check("INFO", "L4 regression guard: the OLD SAML question still retrieves doc-001 and collapses (justifying the swap)",
        "doc-001 retrieved; answer says not enough info", None,
        f"id={old.rows[0]['id'] if old.ok and old.rows else None}; not-enough={bool(NOT_ENOUGH.search(oa))}; answer[:120]={oa[:120]!r}",
        cite(TRAP, "does NOT work"), old)

# ===========================================================================
# 5. LAB 5
# ===========================================================================
section("Lab 5 - rerank")
A5 = ASG[5]
Q5 = "reduce storage cost for old logs"
rrf8 = esql(q_rrf(Q5, 8))
R.check("EXACT", "L5 stage 1 RRF [reduce storage cost for old logs]: doc-041 #1, doc-017 #2", "ids[:2] == [doc-041, doc-017]",
        rrf8.ids[:2] == ["doc-041", "doc-017"], f"top-3={rrf8.top(3)}", cite(TRAP, "in a near-tie for #1 (0.0325 vs 0.0320)"), rrf8)
if rrf8.ok and len(rrf8.rows) >= 2:
    g = abs(rrf8.rows[0]["_score"] - rrf8.rows[1]["_score"])
    R.check("EXACT", "L5 RRF near-tie: |score(#1)-score(#2)| <= 0.001 (docs: 0.0325 vs 0.0320)", "<= 0.001", g <= 0.001,
            f"{rrf8.rows[0]['_score']:.4f} vs {rrf8.rows[1]['_score']:.4f} (gap {g:.4f})", cite(TRAP, "(0.0325 vs 0.0320)"), rrf8)
v3 = esql(q_rerank(Q5, V3))
v2 = esql(q_rerank(Q5, V2))
R.check("EXACT", "L5 RERANK v3 (listwise) flips pick to doc-017", "doc-017 rank 1", v3.ids[:1] == ["doc-017"], f"top-3={v3.top(3)}",
        f"{cite(TRAP, '**listwise (v3) flips to')}; {cite(A5, 'it flips its pick to `doc-017`')}", v3)
R.check("EXACT", "L5 RERANK v2 (pointwise) agrees with RRF: doc-041 stays #1", "doc-041 rank 1", v2.ids[:1] == ["doc-041"], f"top-3={v2.top(3)}",
        cite(TRAP, "**pointwise (v2) agrees with RRF"), v2)
R.check("CLAIM", "L5 rerankers legitimately disagree on the near-tie (v2 #1 != v3 #1)", "v2 top-1 != v3 top-1",
        v2.ids[:1] != v3.ids[:1] and bool(v2.ids), f"v2={v2.ids[:1]} v3={v3.ids[:1]}", cite(TRAP, "reranker types can legitimately disagree"), v2, v3)
# RERANK needs SORT after it
nosort = esql(q_rerank(Q5, V3, sort_after=False))
R.check("CLAIM", "Quirk: RERANK without a following SORT keeps pre-rerank (RRF) ROW ORDER", "ids == RRF ids (same 8 candidates, same order)",
        nosort.ok and rrf8.ok and nosort.ids == rrf8.ids, f"no-sort={nosort.ids[:5]} rrf={rrf8.ids[:5]}",
        cite(HAND, "`RERANK` overwrites `_score` but does NOT reorder"), nosort, rrf8)
if nosort.ok and rrf8.ok:
    R.check("CLAIM", "Quirk: ...but RERANK DID overwrite _score (scores differ from RRF's)", "scores differ",
            nosort.scores() != rrf8.scores(), f"no-sort scores={[round(s, 3) for s in nosort.scores()[:4]]} vs rrf={[round(s, 4) for s in rrf8.scores()[:4]]}",
            cite(TRAP, "overwrites `_score` but does **NOT** reorder"), nosort, rrf8)
R.check("CLAIM", "RERANK + SORT _score DESC: output order differs from RRF order and scores are non-increasing", "order != RRF; scores sorted DESC",
        v3.ok and rrf8.ok and v3.ids != rrf8.ids and v3.scores() == sorted(v3.scores(), reverse=True),
        f"v3 ids={v3.ids[:5]} rrf ids={rrf8.ids[:5]}", cite(TRAP, "**Anywhere `RERANK` appears, `SORT"), v3, rrf8)
# cluster.routing: sharpen decisive stage
Q5b = "cluster.routing.allocation.enable"
rr8 = esql(q_rrf(Q5b, 8))
v3b = esql(q_rerank(Q5b, V3))
R.check("EXACT", "L5 RRF [cluster.routing.allocation.enable]: doc-008 #1 with doc-023 near-tie (<=0.001)",
        "doc-008 #1; doc-023 #2; gap<=0.001", rr8.ids[:2] == ["doc-008", "doc-023"] and abs(rr8.rows[0]["_score"] - rr8.rows[1]["_score"]) <= 0.001 if rr8.ok and len(rr8.rows) > 1 else False,
        f"top-3={rr8.top(3)}", cite(TRAP, "`cluster.routing.allocation.enable`: RRF already ranks"), rr8)
if v3b.ok and len(v3b.rows) >= 2:
    s1, s2 = v3b.rows[0]["_score"], v3b.rows[1]["_score"]
    R.check("EXACT", "L5 RERANK v3 [cluster.routing.allocation.enable]: doc-008 stays #1 and gap widens (docs 0.52 vs 0.09)",
            "doc-008 #1; #1~0.52 (+-0.15); #2~0.09 (+-0.1); gap>=0.3", v3b.ids[:1] == ["doc-008"] and abs(s1 - 0.52) <= 0.15 and abs(s2 - 0.09) <= 0.10 and (s1 - s2) >= 0.3,
            f"top-3={v3b.top(3)} gap={s1 - s2:.3f}", cite(TRAP, "(0.52 vs 0.09)"), v3b)
# pointwise vs listwise: user cannot authenticate
Q5c = "user cannot authenticate"
pw = esql(q_rerank(Q5c, V2))
lw = esql(q_rerank(Q5c, V3))
R.check("EXACT", "L5 [user cannot authenticate] doc-001 (SAML) is #1 for BOTH rerankers", "doc-001 #1 in v2 and v3",
        pw.ids[:1] == ["doc-001"] and lw.ids[:1] == ["doc-001"], f"v2 top-1={pw.ids[:1]} v3 top-1={lw.ids[:1]}",
        cite(TRAP, "`user cannot authenticate` pointwise vs listwise"), pw, lw)
R.check("EXACT", "L5 pointwise v2 ranks doc-002 (authz) #2", "doc-002 rank 2", pw.rank("doc-002") == 2, f"doc-002 rank {pw.rank('doc-002')}; v2 top-5={pw.top(5)}",
        cite(TRAP, "Pointwise ranks `doc-002` (authz) #2"), pw)
R.check("EXACT", "L5 listwise v3 drops doc-002 to #6 (out of top 5)", "doc-002 rank 6", lw.rank("doc-002") == 6, f"doc-002 rank {lw.rank('doc-002')}; v3 top-6={lw.top(6)}",
        cite(TRAP, "listwise drops it to #6"), lw)
R.check("LABTEXT", "L5 page/notebook: listwise 'tends to push [doc-002] down' relative to pointwise", "rank_v3(doc-002) > rank_v2(doc-002)",
        (lw.rank("doc-002") or 99) > (pw.rank("doc-002") or 99), f"v2={pw.rank('doc-002')} v3={lw.rank('doc-002')}", cite(A5, "listwise, scoring the whole set jointly"), pw, lw)

# ===========================================================================
# 6. misc syntax facts used in docs
# ===========================================================================
section("Misc ES|QL syntax claims")
rc = esql(f'-- comment line\nFROM {INDEX}\n| STATS docs = COUNT(*)')
R.check("DERIVED", "Syntax: a '-- ...' comment line (used in TRAP templates and lab2/lab3/lab4 notebook markdown blocks) is accepted by ES|QL",
        "HTTP 200 (if 400, those blocks are not copy-pasteable)", rc.ok, f"HTTP {rc.status}: {rc.error[:100]}",
        cite(TRAP, "-- SEMANTIC"), rc, allow_status=True)
rc2 = esql(f'// comment line\nFROM {INDEX}\n| STATS docs = COUNT(*)')
R.check("INFO", "Syntax: a '// ...' comment line is accepted", "n/a", None, f"HTTP {rc2.status}: {rc2.error[:80]}", "-", rc2, allow_status=True)

# ===========================================================================
# 7. every ```esql block in every assignment.md, verbatim
# ===========================================================================
section("Verbatim assignment.md ```esql blocks")
FENCE = re.compile(r"^\s*```esql\s*$")


def esql_blocks_md(text):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if FENCE.match(lines[i]):
            start = i + 2  # 1-based line number of first content line
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            yield start, "\n".join(body)
        i += 1


def run_block(label, src, q_text, subst, expect_top1=None, expect_note=""):
    rr = esql(q_text, timeout=300)
    status = "ok" if rr.ok else f"HTTP {rr.status}"
    verdict = "PASS" if rr.ok else "FAIL"
    note = ""
    if rr.ok and expect_top1:
        if rr.ids[:1] == [expect_top1]:
            note = f"top-1 == {expect_top1} as expected"
        else:
            verdict = "FAIL"
            note = f"expected top-1 {expect_top1}, got {rr.ids[:1]}"
    elif not rr.ok:
        note = rr.error[:160]
    if rr.ok and "answer" in rr.names and rr.rows:
        note += f" answer_len={len(str(rr.rows[0].get('answer') or ''))}"
    R.blocks.append({"label": label, "src": src, "subst": subst, "http": rr.status, "rows": len(rr.rows) if rr.ok else 0,
                     "top5": rr.top(5) if rr.ok else "-", "verdict": verdict, "note": (note + " " + expect_note).strip(),
                     "elapsed": round(rr.elapsed, 1)})
    print(f"  [{verdict:<4}] {label:<12} {src:<44} http={rr.status} rows={len(rr.rows) if rr.ok else 0} {note[:80]}", flush=True)
    return rr


for n in range(1, 6):
    text = ASG[n].read_text(encoding="utf-8")
    for bi, (ln, body) in enumerate(esql_blocks_md(text), 1):
        subst = ""
        q_text = body
        if "?q" in q_text:
            q_text = q_text.replace("?q", lit(ILM_Q))
            subst = f"?q -> {ILM_Q[:40]}..."
        if re.search(r"<[A-Za-z ]+>", q_text):
            subst += " [UNRESOLVED <placeholder>]"
        run_block(f"L{n}#{bi}", f"{ASG[n].parent.name}/assignment.md:{ln}", q_text, subst)
        # variants the lab text tells the learner to try
        if n == 3 and "FUSE\n| SORT _score DESC\n| LIMIT 5" in body and "notify me" in body:
            for q2, tgt in (("8.18 breaking changes", "doc-057"), ("new_primaries", "doc-008"), ("exit code 137", "doc-007")):
                run_block(f"L3#{bi}-swap", f"L3 Part A, query swapped in both branches -> {q2}", body.replace("notify me when something goes wrong", q2), "", tgt)
        if n == 3 and "FUSE LINEAR" in body:
            run_block(f"L3#{bi}-flip", "L3 Part B flipped to 0.3/0.7", body.replace('"fork1": 0.8, "fork2": 0.2', '"fork1": 0.3, "fork2": 0.7'), "", "doc-049")
        if n == 5 and "RERANK" in body:
            run_block(f"L5#{bi}-v2", "L5 inference_id -> v2 pointwise", body.replace(V3, V2), "", "doc-041", "(docs: v2 keeps doc-041)")
            run_block(f"L5#{bi}-auth", "L5 pointwise/listwise on 'user cannot authenticate' (v3)", body.replace("reduce storage cost for old logs", "user cannot authenticate"), "", "doc-001")
            run_block(f"L5#{bi}-auth-v2", "L5 pointwise on 'user cannot authenticate' (v2)", body.replace("reduce storage cost for old logs", "user cannot authenticate").replace(V3, V2), "", "doc-001")

section("Notebook markdown ```esql blocks (informational: shown to learners, run as written)")
NB_SUBST = {1: None, 2: None, 3: "breaking changes", 4: ILM_Q, 5: None}
for n in range(1, 6):
    nb = json.load(open(NB[n]))
    for ci, c in enumerate(nb["cells"]):
        if c["cell_type"] != "markdown":
            continue
        for bi, (ln, body) in enumerate(esql_blocks_md("".join(c["source"])), 1):
            first = [l for l in body.splitlines() if l.strip() and not l.strip().startswith("--")]
            if not first or not first[0].lstrip().upper().startswith("FROM") or f"{INDEX}" not in body:
                R.blocks.append({"label": f"NB{n}c{ci}#{bi}", "src": f"{NB[n].name} cell {ci}", "subst": "", "http": "-", "rows": 0, "top5": "-",
                                 "verdict": "SKIP", "note": "fragment / illustration (not a full query)", "elapsed": 0})
                print(f"  [SKIP] NB{n}c{ci}#{bi:<2} {NB[n].name} cell {ci}: fragment", flush=True)
                continue
            q_text = body
            subst = ""
            if "?q" in q_text:
                q_text = q_text.replace("?q", lit(NB_SUBST[n] or ILM_Q))
                subst = f"?q -> {(NB_SUBST[n] or ILM_Q)[:30]}"
            if "<completion endpoint>" in q_text:
                q_text = q_text.replace("<completion endpoint>", f'"{COMPLETION_ID}"')
                subst += " <completion endpoint> -> haiku id"
            run_block(f"NB{n}c{ci}#{bi}", f"{NB[n].name} cell {ci}", q_text, subst)

# ===========================================================================
# report
# ===========================================================================
rows = R.rows
counts = {}
for r_ in rows:
    counts[r_["status"]] = counts.get(r_["status"], 0) + 1
gating = [r_ for r_ in rows if r_["level"] in ("EXACT", "CLAIM", "LABTEXT") and r_["status"] in ("FAIL", "ERROR")]
blk_fail = [b for b in R.blocks if b["verdict"] == "FAIL"]

md = []
md.append("# ES|QL workshop claims -- results\n")
md.append(f"_generated {time.strftime('%Y-%m-%d %H:%M:%S')} against ES host `{common.host_of(os.environ['ES_ENDPOINT'])}`_\n")
md.append(f"**Assertions:** {len(rows)}  |  PASS {counts.get('PASS', 0)}  |  FAIL {counts.get('FAIL', 0)}  |  ERROR {counts.get('ERROR', 0)}  |  INFO {counts.get('INFO', 0)}  "
          f"|  gating failures (EXACT/CLAIM/LABTEXT): **{len(gating)}**\n")
md.append(f"**Verbatim blocks:** {len(R.blocks)}  |  PASS {sum(b['verdict'] == 'PASS' for b in R.blocks)}  |  FAIL {len(blk_fail)}  |  SKIP {sum(b['verdict'] == 'SKIP' for b in R.blocks)}\n")
md.append("Levels: EXACT = exact rank/score in TRAP/HANDOFF doc; CLAIM = teaching claim in docs; LABTEXT = said to the learner in assignment/notebook; "
          "DERIVED = inferred by this harness (never gates); INFO = observation.\n")
md.append("\n## Assertions\n")
md.append("| # | Level | Assertion | Expected | Actual | Result | Source |")
md.append("|---|---|---|---|---|---|---|")


def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


for r_ in rows:
    md.append(f"| {r_['n']} | {r_['level']} | {esc(r_['name'])} | {esc(r_['expected'])} | {esc(r_['actual'])[:220]} | **{r_['status']}** | {esc(r_['cite'])} |")
md.append("\n## Failure details (actual top-5 ids with scores)\n")
any_fail = False
for r_ in rows:
    if r_["status"] in ("FAIL", "ERROR"):
        any_fail = True
        md.append(f"**#{r_['n']} {r_['level']} -- {r_['name']}**  \nexpected: {r_['expected']}  \nactual: {r_['actual']}  \nsource: {r_['cite']}")
        for d in r_["detail"]:
            md.append(f"- top-5: `{d['top5']}`")
            if d["query"]:
                md.append("  ```esql\n  " + d["query"].replace("\n", "\n  ") + "\n  ```")
        md.append("")
if not any_fail:
    md.append("_none_\n")
md.append("\n## Every ```esql block run verbatim\n")
md.append("| Label | Source | Substitution | HTTP | Rows | Top-5 ids (score) | Result | Note | s |")
md.append("|---|---|---|---|---|---|---|---|---|")
for b in R.blocks:
    md.append(f"| {b['label']} | {esc(b['src'])} | {esc(b['subst'])} | {b['http']} | {b['rows']} | {esc(b['top5'])} | **{b['verdict']}** | {esc(b['note'])[:200]} | {b['elapsed']} |")
(common.OUT).mkdir(parents=True, exist_ok=True)
(common.OUT / "claims.md").write_text("\n".join(md), encoding="utf-8")
(common.OUT / "claims_raw.json").write_text(json.dumps({"assertions": rows, "blocks": R.blocks}, indent=2, default=str))
print(f"\nSUMMARY: {len(rows)} assertions: PASS {counts.get('PASS', 0)} FAIL {counts.get('FAIL', 0)} ERROR {counts.get('ERROR', 0)} INFO {counts.get('INFO', 0)}; "
      f"gating failures {len(gating)}; blocks FAIL {len(blk_fail)}/{len(R.blocks)}")
print(f"report: {common.OUT / 'claims.md'}")
sys.exit(1 if (gating or blk_fail) else 0)
