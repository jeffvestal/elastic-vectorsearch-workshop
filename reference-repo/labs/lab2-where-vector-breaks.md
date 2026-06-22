# Lab 2 — Where Vector Breaks (and Lexical's Own Gap)

See `instruqt/02-where-vector-breaks/assignment.md` for the full walkthrough.
All Dev Console snippets are in `instruqt/02-where-vector-breaks/queries.md`.

---

## Quick Reference

### Part A: Adversarial semantic queries (vector fails)

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

Try these queries where vector struggles:
- `exit code 137` — exact error code
- `8.18 breaking changes` — version string (vector blurs 8.15/8.18/9.0)
- `xpack.security.authc.realms configuration` — exact setting name

### Part B: BM25 rescue (multi_match on exact tokens)

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

### Part C: The paraphrase pair (vector wins, BM25 fails)

**Semantic (wins):**
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
Expected: doc-001 (SAML auth troubleshooting) at rank 1–2

**BM25 (fails):**
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
Expected: doc-001 NOT in top 5 (BM25 score = 0, no matching tokens)

---

## The Core Tension

| Method | Wins at | Fails at |
|--------|---------|---------|
| Vector | Natural language, paraphrases, intent | Exact tokens, version numbers, codes, settings |
| BM25 | Exact tokens, version strings, codes | Natural language, paraphrases, synonyms |

You need both.
