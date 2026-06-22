# Lab 3 — Dev Console Snippets

---

## Part A — RRF Hybrid Retriever

### A1 — RRF on "exit code 137" (BM25 trap — hybrid wins)

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
                "query": "exit code 137",
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
                "query": "exit code 137"
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
  "_source": ["id", "title"]
}
```
// Expected: doc-007 at rank 1
// BM25 sub-retriever pins it (exact token); semantic sub-retriever contributes from its neighborhood
// RRF fuses by rank position — doc-007 wins

---

### A2 — RRF on "8.18 breaking changes" (version trap — hybrid wins)

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
                "query": "8.18 breaking changes",
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
                "query": "8.18 breaking changes"
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
  "_source": ["id", "title", "version_tags"]
}
```
// Expected: doc-057 (8.18) at rank 1, clear margin over doc-058 (8.15) and doc-006 (9.0)
// BM25 pins "8.18" as an exact token; semantic adds broad relevance
// RRF fusion: doc-057 gets high combined score from BM25 pinning

---

### A3 — RRF on "user can't log in" (paraphrase trap — hybrid wins)

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
// Expected: doc-001 (SAML auth troubleshooting) at rank 1 or 2
// Semantic sub-retriever puts doc-001 at rank 1 (paraphrase match)
// BM25 misses doc-001 (score ~0) but doesn't actively hurt it in RRF — semantic contribution wins
// RRF: a doc that appears only in the semantic list still contributes from that rank position

---

### A4 — RRF on "xpack.security.authc.realms configuration" (setting trap — hybrid wins)

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
                "query": "xpack.security.authc.realms configuration",
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
                "query": "xpack.security.authc.realms configuration"
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
  "_source": ["id", "title"]
}
```
// Expected: pages with the exact setting name at rank 1-2
// BM25 pins exact setting token; semantic adds related auth/realm docs

---

### A5 — Tune rank_constant (experiment)

Try rank_constant: 1 vs rank_constant: 100 on any of the above queries.
Lower = stronger winner-take-all. Higher = more blending.

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
                "query": "exit code 137",
                "fields": ["title^3", "body"]
              }
            }
          }
        },
        {
          "standard": {
            "query": {
              "semantic": {
                "field": "body_semantic",
                "query": "exit code 137"
              }
            }
          }
        }
      ],
      "rank_constant": 1,
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

---

## Part B — Linear Retriever (Score-Based Fusion)

### B1 — Linear hybrid, equal weights

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
  "_source": ["id", "title", "trap_type"]
}
```
// normalizer: "minmax" → each sub-retriever's scores normalized to [0,1] before weighting
// Equal weights → similar behavior to RRF on this query
// Expected: doc-001 at rank 1-2

---

### B2 — Linear hybrid, BM25-heavy (tune for exact-token queries)

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
                  "query": "8.18 breaking changes",
                  "fields": ["title^3", "body"],
                  "type": "best_fields"
                }
              }
            }
          },
          "weight": 0.8
        },
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
          "weight": 0.2
        }
      ],
      "normalizer": "minmax",
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "version_tags"]
}
```
// BM25 weight: 0.8, semantic weight: 0.2 — strong preference for exact-token matches
// Expected: doc-057 at rank 1 with an even larger margin

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
// text_similarity_reranker: wraps the full RRF hybrid retriever
// Gets top 50 results from hybrid, reranks with Jina Reranker v2 cross-encoder via EIS
// Cross-encoder: more accurate than bi-encoder for ranking, but too expensive to run over full corpus
// Use pattern: hybrid first (fast, cheap) → rerank top-N (expensive but small)
// Full take-home version: reference-repo/labs/lab3-hybrid.md
