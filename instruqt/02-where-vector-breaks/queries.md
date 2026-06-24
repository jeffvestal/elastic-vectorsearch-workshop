# Lab 2 — Dev Console Snippets

All ranks below were verified live against the 62-doc workshop corpus (Jina v5, ES 9.5.0).

---

## Part A — Semantic blurs / mis-ranks exact identifiers

### A1 — Exit code (semantic *blurs*, near-tie)

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
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-007 #1 (~0.680) but a `distractor` doc (doc-061) is #2 at ~0.678 — a ~0.001 gap.
// Top 5 all within ~0.05. The number "137" barely discriminates; ranking is essentially noise.
// Two distractor docs (doc-061, doc-062) describe exit codes / crashes WITHOUT the literal "137".

---

### A2 — Bare config value (semantic returns the WRONG doc)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "new_primaries"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: #1 is doc-021 (Red/yellow cluster health) — WRONG. doc-008 (shard allocation,
// where new_primaries is documented) is only #2. Right neighborhood, wrong document.

---

### A3 — Distinctive dotted key (semantic gets it RIGHT — honesty check)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "cluster.routing.allocation.enable"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-008 #1 (~0.79). A long, distinctive dotted key embeds well.
// Lesson: exact identifiers are a RELIABILITY problem for vectors, not a guaranteed miss.

---

## Part B — BM25 is decisive on exact tokens, but mis-ranks a boosted title

### B1 — Exit code (BM25 wins decisively)

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
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-007 #1 by a WIDE margin (~8.4 vs ~6.1, cliff after).
// "137" is rare (high IDF) and lives only in doc-007 → BM25 pins it unambiguously.

---

### B2 — Version string (BM25 ranks the WRONG doc)

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
// Expected: doc-006 "Elasticsearch breaking changes" #1 (~12.9) — WRONG.
// doc-057 (8.18 release notes), the doc the user wants, is only #2 (~7.4).
// WHY: doc-006's TITLE is literally "breaking changes" and title is ^3-boosted
// (title:breaking ~6.5 + title:changes ~6.5 = ~12.9). doc-057 matches rare "8.18"
// (~5.8) but its title lacks "breaking changes". Field-boost effect, NOT term frequency.
// Run the SAME query as semantic (A-style) → doc-057 #1. They fail on opposite shapes.

---

## Part C — Paraphrase: BM25 buries it, semantic finds it

### C1 — "notify me when something goes wrong" → Semantic wins

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "notify me when something goes wrong"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-049 (Watcher alerting) #1 (~0.75).
// doc-049 body uses trigger/condition/actions/webhook — NONE of the query words.
// Semantic maps query and doc to the same region by MEANING.

---

### C2 — "notify me when something goes wrong" → BM25 buries it

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "notify me when something goes wrong",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-049 NOT in the top few (buried ~#5). Top BM25 hits share an incidental
// common word, not the alerting concept. None of {notify, something, goes, wrong}
// appear in doc-049, so its score is tiny.
// Note: BURIED, not "zero" — a real index still returns it, just too low to be useful.

// THE AHA: doc-049 describes exactly what the user wants. BM25 can't surface it; semantic can.
// And on B2, semantic was right where BM25 was wrong. You need both.
