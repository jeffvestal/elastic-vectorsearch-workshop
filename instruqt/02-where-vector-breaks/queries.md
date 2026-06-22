# Lab 2 — Dev Console Snippets

---

## Part A — Semantic Queries That Fail on Exact Tokens

### A1 — Exit Code (semantic fails)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "exit code 137"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```
// Expected: doc-007 (JVM settings, exit code 137) NOT at rank 1
// Vector maps "exit code 137" → memory/JVM concepts → returns similar-topic but wrong docs

---

### A2 — Version String (semantic blurs versions)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "8.18 breaking changes"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "version_tags"]
}
```
// Expected: doc-057 (8.18), doc-058 (8.15), doc-006 (9.0) all appear with similar scores
// Vector treats all three "breaking changes" pages as semantically equivalent — can't pin version

---

### A3 — Exact Setting Name (semantic approximates)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "xpack.security.authc.realms configuration"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```
// Expected: generic security/config docs — not the exact page with this setting name
// The dotted setting name gets embedded as "security authentication" semantics — misses the exact match

---

## Part B — BM25 Rescue (exact tokens win)

### B1 — Exit Code (BM25 wins)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "exit code 137",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```
// Expected: doc-007 at rank 1
// BM25: "137" is rare in the corpus (high IDF) → exact match scores top

---

### B2 — Version String (BM25 pins version)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "8.18 breaking changes",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "version_tags"]
}
```
// Expected: doc-057 (8.18 release notes) at rank 1 with a clear margin
// "8.18" is an exact token — BM25 IDF rewards the doc that says "8.18" specifically

---

### B3 — Exact Setting Name (BM25 wins)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "xpack.security.authc.realms configuration",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```
// Expected: doc-001, doc-005 (pages with exact realm config setting names) rank top
// "xpack.security.authc.realms" is a very high-IDF rare token — BM25 pins the right docs

---

## Part C — The Paraphrase Pair (HIGHEST-RISK LIVE MOMENT)

### C1 — "user can't log in" → Semantic wins

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "user can't log in"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```
// Expected: doc-001 (SAML authentication troubleshooting) at rank 1 or 2
// WHY it works: "user can't log in" ≈ "authentication failure, credential error, realm config" in Jina v5 embedding space
// doc-001 body: 0 occurrences of "log in" / "login" — 29+ occurrences of "authentication", "credential", "realm"

---

### C2 — "user can't log in" → BM25 fails

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "user can't log in",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```
// Expected: doc-001 NOT in top 5
// WHY it fails: BM25 tokenizes {"user", "can't", "log", "in"} — doc-001 contains none of these as authentication terms
// BM25 score for doc-001 = 0 (or very low from "user" appearing in unrelated context)
// BM25 returns docs with "user" or "in" in title — semantically wrong

// THIS IS THE AHA MOMENT: doc-001 describes exactly the user's problem. BM25 can't find it.
// You need both methods.
