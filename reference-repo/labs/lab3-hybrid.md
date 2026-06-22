# Lab 3 — Hybrid: Best of Both (RRF + Linear Combination)

See `instruqt/03-hybrid-search/assignment.md` for the full walkthrough.
All Dev Console snippets are in `instruqt/03-hybrid-search/queries.md`.

---

## Quick Reference

### RRF Hybrid Retriever

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
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
        {
          "standard": {
            "query": {
              "semantic": {
                "field": "body_semantic",
                "query": "user can't log in"
              }
            }
          }
        }
      ],
      "rank_constant": 60,
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

Change `"user can't log in"` in BOTH sub-retrievers to try other queries.

### Linear Hybrid Retriever (score-based, with weights)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "linear": {
      "retrievers": [
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
          "weight": 0.5
        },
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
          "weight": 0.5
        }
      ],
      "normalizer": "minmax",
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

Tune `weight` on each sub-retriever. BM25 weight 0.8 + semantic weight 0.2 for exact-token heavy workloads.

### Reranker (take-home, requires Jina Reranker v2 on EIS)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [
            {
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
            {
              "standard": {
                "query": {
                  "semantic": {
                    "field": "body_semantic",
                    "query": "user can't log in"
                  }
                }
              }
            }
          ],
          "rank_constant": 60,
          "rank_window_size": 100
        }
      },
      "field": "body",
      "inference_id": ".jina-reranker-v2-base-multilingual",
      "inference_text": "user can't log in",
      "rank_window_size": 50
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

Note: verify the exact `inference_id` for Jina Reranker v2 in your Serverless project (`GET _inference`).

---

## RRF vs Linear — When to Use Each

| | RRF | Linear |
|---|---|---|
| Score normalization | Not needed (rank-based) | MinMax built-in |
| Tuning | None required (60 default) | Weights per sub-retriever |
| Production default | Yes | When you have calibrated weights |
