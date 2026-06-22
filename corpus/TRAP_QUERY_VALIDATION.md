# Trap Query Validation

Pre-event checklist: run every query below against the live index before the workshop.
Document actual results in the "Verified" column.

---

## Lab 2 Part A — Adversarial Queries (Vector Should FAIL, BM25 Should WIN)

These queries expose pure vector's blind spots: exact tokens, version strings, error codes.
Run them as `standard` + `semantic` queries. Expect poor/wrong results.

### Trap Query A1 — Exit Code

**Query:** `exit code 137`
**Target doc:** `doc-007` (JVM settings — mentions OOM killer / exit code 137)
**Why vector fails:** "exit code 137" is a Linux signal/numeric token. Vector embeds it as a semantic concept near "memory issues" and "JVM crashes" — returns topically similar but not exact matches. The exact doc may not rank #1.
**Why BM25 wins:** exact term match on "137" and "exit code" → doc-007 scores top.

**Verification:**
- [ ] Run as semantic query — does doc-007 rank #1? (expected: No, or low rank)
- [ ] Run as match query — does doc-007 rank #1? (expected: Yes)
- [ ] Contrast is clear to audience? (expected: Yes)

---

### Trap Query A2 — Version String

**Query:** `8.18 breaking changes`
**Target doc:** `doc-057` (Elasticsearch 8.18 release notes)
**Why vector fails:** vector blurs 8.15 / 8.18 / 9.0 — all three version pages are semantically similar ("breaking changes, deprecated APIs, migration") so vector returns a mix.
**Why BM25 wins:** exact "8.18" term match pins the correct version page.

**Verification:**
- [ ] Run as semantic query — do all three version docs (doc-006, doc-057, doc-058) appear with roughly similar scores? (expected: yes, blurred)
- [ ] Run as match query — does doc-057 rank #1 by a clear margin? (expected: yes)

---

### Trap Query A3 — Exact Setting Name

**Query:** `xpack.security.authc.realms configuration`
**Target doc:** `doc-008` (cluster allocation settings) or `doc-001` / `doc-005` (realm config pages)
**Why vector fails:** vector returns any security/config doc; it doesn't nail the exact dotted setting name.
**Why BM25 wins:** the exact token `xpack.security.authc.realms` is a rare, high-IDF term — BM25 pins the page(s) that contain it.

**Verification:**
- [ ] Run as semantic query — does the response include irrelevant security docs that don't mention this setting? (expected: yes)
- [ ] Run as match/multi_match query — does response narrow to docs with the exact setting string? (expected: yes)

---

## Lab 2 Part C — Paraphrase Pair (Vector Should WIN, BM25 Should FAIL)

This is the highest-risk live moment. Pre-test against the REAL index. Do not assume.

### The Paraphrase Trap

**Query:** `user can't log in`

**Target doc:** `doc-001` (SAML authentication troubleshooting)

**Vocabulary analysis of doc-001:**
- Contains: "authentication failure", "credential error", "realm configuration", "xpack.security.authc.realms", "SAML response", "principal attribute", "IdP metadata"
- Does NOT contain (verified): "log in", "login", "can't login", "login failed"
- Login-related mentions: 0
- Auth/credential/realm mentions: 29+

**Why vector WINS:**
The semantic meaning of "user can't log in" = "user authentication is failing" = "authentication failure, credential error" — Jina v5 maps these into the same embedding neighborhood. Vector finds doc-001 at rank 1 or 2 even though "log in" never appears.

**Why BM25 FAILS:**
BM25 tokenizes "user can't log in" → {user, can't, log, in}. None of these tokens appear in doc-001 (verified: 0 matches). BM25 score for doc-001 = 0. BM25 returns unrelated docs that happen to contain "user" or "in".

**Expected results:**
```
Semantic query:  doc-001 rank #1 (or #2)  ← vector wins
BM25 query:      doc-001 not in top 10    ← BM25 whiffs
```

**Pre-event validation steps:**
1. Run ingest.py — verify doc-001 indexed with body_semantic populated
2. Run: `GET aiewf-workshop-docs/_search` with `standard` + `semantic` query for "user can't log in"
3. Confirm doc-001 appears in top 3
4. Run: `GET aiewf-workshop-docs/_search` with `standard` + `multi_match` for "user can't log in"
5. Confirm doc-001 is NOT in top 5 (if it appears, check its body for unexpected login tokens)

**Fallback if doc-001 breaks:**
doc-002 (authorization errors / role mapping) is a secondary paraphrase candidate — also uses "authorization failure", "role mapping", "realm configuration" without "log in". Use as backup.

---

## Lab 3 Verification — Hybrid Should WIN on ALL Traps

After building the RRF retriever, re-run ALL four queries above through hybrid.
Hybrid should rank each target doc at #1 or #2.

| Query | Target Doc | Semantic Rank | BM25 Rank | Hybrid Rank |
|---|---|---|---|---|
| `exit code 137` | doc-007 | (pre-test) | (pre-test) | (pre-test) |
| `8.18 breaking changes` | doc-057 | (pre-test) | (pre-test) | (pre-test) |
| `xpack.security.authc.realms configuration` | doc-001/doc-008 | (pre-test) | (pre-test) | (pre-test) |
| `user can't log in` | doc-001 | (pre-test) | (pre-test) | (pre-test) |

Fill in actual ranks during pacing dry-run. If hybrid doesn't win all 4, adjust `rank_constant` or field boosts.

---

## Lab 1 — "Wow" Query Verification

These should return semantically relevant docs even though the query words don't appear in the title/body.

| Query | Expected top result | Why it works |
|---|---|---|
| `securing cluster traffic` | doc about TLS/SSL | semantic: "securing traffic" ≈ "TLS encryption" |
| `how do I make my cluster not lose data` | snapshot/ILM doc | semantic: "lose data" ≈ "backup, snapshot, retention" |
| `users can't reach Kibana` | Kibana network/config doc | semantic: "can't reach" ≈ "connection refused, network access, proxy" |

Verify these give satisfying results before the event. If a query returns garbage, swap it out in the lab instructions.
