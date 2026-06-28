# Lab 3 — Dev Console Snippets

All ranks verified live against the 62-doc corpus (Jina v5, ES 9.5.0). RRF lands the
correct doc at #1 on every trap query below — even where one sub-retriever mis-ranked it.

---

## Part A — RRF Hybrid Retriever

### A1 — RRF on "notify me when something goes wrong" (paraphrase — BM25 buried it)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": {
          "query": "notify me when something goes wrong",
          "fields": ["title^3", "body"], "type": "best_fields" } } } },
        { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "notify me when something goes wrong" } } } }
      ],
      "rank_constant": 60, "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-049 (Watcher alerting) at rank 1.
// Semantic ranked it #1; BM25 buried it (~#5). RRF needs only one strong vote → doc-049 wins.

---

### A2 — RRF on "8.18 breaking changes" (version — BM25 ranked the WRONG doc)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": {
          "query": "8.18 breaking changes",
          "fields": ["title^3", "body"], "type": "best_fields" } } } },
        { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "8.18 breaking changes" } } } }
      ],
      "rank_constant": 60, "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "version_tags"]
}
```
// Expected: doc-057 (8.18 release notes) at rank 1.
// BM25 alone put the WRONG doc first (doc-006 "breaking changes", boosted title); semantic ranked
// doc-057 #1. RRF fuses the two and doc-057 wins.

---

### A3 — RRF on "new_primaries" (bare value — SEMANTIC picked the wrong doc)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": {
          "query": "new_primaries",
          "fields": ["title^3", "body"], "type": "best_fields" } } } },
        { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "new_primaries" } } } }
      ],
      "rank_constant": 60, "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-008 (shard allocation settings) at rank 1.
// Here SEMANTIC was wrong (it put a cluster-health doc #1); BM25 pinned doc-008. RRF recovers it.
// Together A1/A2/A3 show RRF wins whether semantic OR BM25 was the one that failed.

---

### A4 — RRF on "exit code 137" (exact id — semantic blurred, BM25 decisive)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": {
          "query": "exit code 137",
          "fields": ["title^3", "body"], "type": "best_fields" } } } },
        { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "exit code 137" } } } }
      ],
      "rank_constant": 60, "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// Expected: doc-007 at rank 1.
// Semantic was a near-tie (distractors ~0.001 behind); BM25 pinned doc-007 decisively via "137".
// RRF keeps doc-007 #1.

---

### A5 — Tune rank_constant (experiment)

Try `rank_constant: 1` vs `rank_constant: 100` on any query above.
Lower = stronger winner-take-all. Higher = more blending across the two lists.

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": {
          "query": "notify me when something goes wrong",
          "fields": ["title^3", "body"] } } } },
        { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "notify me when something goes wrong" } } } }
      ],
      "rank_constant": 1, "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

---

## Part B — Linear Retriever (Score-Based Fusion)

### B1 — Linear, paraphrase query: weights change the winner

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "linear": {
      "retrievers": [
        { "retriever": { "standard": { "query": { "multi_match": {
          "query": "notify me when something goes wrong",
          "fields": ["title^3", "body"], "type": "best_fields" } } } }, "weight": 0.5 },
        { "retriever": { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "notify me when something goes wrong" } } } }, "weight": 0.5 }
      ],
      "normalizer": "minmax", "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```
// At 0.5/0.5: a lexical distractor (doc-061) can edge out doc-049 at #1.
// Bump semantic to 0.7 / BM25 to 0.3 → doc-049 returns to #1.
// minmax rescales each retriever to [0,1] so weights are honest; linear weighs MAGNITUDE, not just rank.

---

### B2 — Linear, version query: the "obvious" weight backfires

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "linear": {
      "retrievers": [
        { "retriever": { "standard": { "query": { "multi_match": {
          "query": "8.18 breaking changes",
          "fields": ["title^3", "body"], "type": "best_fields" } } } }, "weight": 0.8 },
        { "retriever": { "standard": { "query": { "semantic": {
          "field": "body_semantic", "query": "8.18 breaking changes" } } } }, "weight": 0.2 }
      ],
      "normalizer": "minmax", "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "version_tags"]
}
```
// "It's a version string, lean on BM25" → WRONG. At 0.8/0.2 the wrong doc (doc-006) stays #1,
// because BM25 itself is wrong here (boosted-title match). Flip to BM25 0.2 / semantic 0.8 → doc-057 #1.
// Lesson: no single weight is right for every query; RRF (no weights) is the robust default.

---

## Part C — Reranker (Pre-Run / Instructor Demo / Take-Home)

```
// Pre-run — instructor runs this, attendees observe
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            { "standard": { "query": { "multi_match": {
              "query": "how do I secure traffic between nodes",
              "fields": ["title^3", "body"], "type": "best_fields" } } } },
            { "standard": { "query": { "semantic": {
              "field": "body_semantic", "query": "how do I secure traffic between nodes" } } } }
          ],
          "rank_constant": 60, "rank_window_size": 100
        }
      },
      "field": "body",
      "inference_id": ".jina-reranker-v2-base-multilingual",
      "inference_text": "how do I secure traffic between nodes",
      "rank_window_size": 50
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```
// text_similarity_reranker wraps the full RRF hybrid retriever.
// Gets the top 50 from hybrid, reranks with Jina Reranker v2 cross-encoder via EIS.
// Cross-encoder: more accurate than a bi-encoder, too expensive to run over the full corpus.
// Pattern: hybrid first (fast, cheap) → rerank top-N (expensive, small).
// NOTE: on a 62-doc corpus RRF already nails #1, so reranking has little room to help — and may
// shuffle a lexically-similar distractor up. This is a MECHANICS demo; the payoff is real at scale.
//
// → Go deeper in the bonus Lab 5 (notebooks/lab5-reranking.ipynb): the rerank API called directly,
//   pointwise (cross-encoder) vs listwise rerankers, Jina Reranker v2 vs v3, and when to use which.
