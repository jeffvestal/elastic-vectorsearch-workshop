---
slug: hybrid-search
id: aiewf2026-lab3
type: challenge
title: "Lab 3 — Hybrid: Best of Both (RRF + Linear Combination)"
teaser: Compose BM25 and semantic into one retriever. Learn two fusion strategies — RRF and linear combination — and build a production-grade hybrid retriever.
tabs:
- id: kibana-console
  title: Kibana Dev Console
  type: service
  hostname: serverless
  path: /app/dev_tools#/console
  port: 443
difficulty: intermediate
timelimit: 1800
---

# Lab 3 — Hybrid: Best of Both

**Time budget: ~40 minutes** (this is the heart of the workshop)

---

## What You're Building

A production-grade hybrid retriever that combines BM25 and semantic search.
Run every Lab 2 trap query through it — hybrid should win on all of them simultaneously.

You'll build two fusion strategies:
- **RRF** — Reciprocal Rank Fusion: rank-based, no score normalization needed, robust zero-tuning default
- **Linear** — score-based, weighted, with MinMax normalization; more control when you can calibrate

---

## Why Hybrid?

Lab 2 proved the core tension:
- Vector wins on paraphrases ("user can't log in" → authentication failure doc)
- BM25 wins on exact tokens ("exit code 137", "8.18", `xpack.security.authc.realms`)

Hybrid fuses both ranked lists so you get **both** wins simultaneously.

The retriever API in Elasticsearch lets you compose sub-retrievers inside a parent retriever. The parent handles fusion. Let's build it.

---

## Part A — RRF (Reciprocal Rank Fusion)

RRF fuses two ranked lists without normalizing scores. It works by giving each doc a score based on its rank in each list:

```
RRF score = sum over each list of: 1 / (rank_constant + rank)
```

A doc ranked #1 in BM25 and #3 in semantic beats a doc that appears in only one list. `rank_constant` (default 60) controls how much early ranks are rewarded.

**Advantages of RRF:**
- Doesn't require score normalization (BM25 and vector scores are on completely different scales — RRF sidesteps this)
- Works well with no tuning; the 60 default is robust across most corpora
- The zero-tuning default for production hybrid search

### Build the RRF retriever

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

**Expected:** doc-007 at rank #1. Hybrid wins because:
- BM25 puts doc-007 at rank #1 (exact token match)
- Semantic puts doc-007 somewhere in the top 10 (JVM/memory semantic neighborhood)
- RRF combines both lists — doc-007 gets a high combined score

### Try the paraphrase query through RRF

Change the `"query"` strings on both sub-retrievers to `"user can't log in"`.
Expected: doc-001 at rank #1 or #2. Hybrid wins because:
- Semantic puts doc-001 at rank #1 (paraphrase match)
- BM25 puts doc-001 at rank 0 (missing, so it doesn't penalize much)
- The semantic contribution still pushes doc-001 to the top

### Tune the rank_constant

Try `rank_constant: 1` vs `rank_constant: 100`:
- Lower constant: early ranks get much higher weight → winner-take-all behavior
- Higher constant: rank differences matter less → more blending

For most corpora, 60 is fine. Change it only if you have query data showing a specific behavior you want.

---

## Part B — Linear Combination (Score-Based Fusion)

Linear fusion multiplies sub-retriever scores by configurable weights and sums them. It's the "more control" option — but it requires score normalization since BM25 and vector scores are on different scales.

Elasticsearch's `linear` retriever handles normalization via `normalizer: "minmax"`:
- Each sub-retriever's scores are normalized to [0, 1] before weighting
- Then weighted and summed

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
                  "query": "exit code 137",
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
                  "query": "exit code 137"
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

**Observe:** with equal weights (0.5 / 0.5), this should behave similarly to RRF. Now try shifting the weights.

### Experiment: Shift weights for exact-token queries

For queries you know are exact-token (version strings, error codes), try `"weight": 0.8` for BM25 and `"weight": 0.2` for semantic:

Change the weights in the query above and re-run. You should see even stronger pinning on the exact doc.

### RRF vs Linear — When to Use Each

| | RRF | Linear |
|---|---|---|
| Score normalization needed | No | Yes (MinMax built-in) |
| Tuning required | No (60 default works) | Yes (weights per sub-retriever) |
| Score meaning | Rank position only | Actual score magnitude |
| Best when | Zero-tuning default, unknown corpus | You have query data, can calibrate weights |
| Production default | Yes | When you need more control |

**The practical rule:** start with RRF. Switch to linear only when you have a specific reason (e.g., you've measured that BM25 should dominate for your query distribution, or you want to add a third sub-retriever with a specific contribution weight).

---

## Part C — Reranker (Pre-Run / Take-Home)

**Instructor will run this live — you do not need to run it yourself.**

A `text_similarity_reranker` wraps the hybrid retriever and re-scores the top-N results using a cross-encoder model (Jina Reranker v2 via EIS). Cross-encoders are more accurate than bi-encoders for ranking but too expensive to run over the full corpus — so you run hybrid retrieval first (cheap, fast), then rerank the top 50–100 results (expensive but small).

```
// Pre-run cell — instructor-driven
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

Same EIS story as Lab 1 — the reranker model also runs server-side. No client-side cross-encoder inference. Full take-home version lives in the reference repo.

---

## End State

You now have a production-grade hybrid retriever. Run all four Lab 2 trap queries through the RRF retriever:

| Query | Lab 2 Winner | Lab 3 Hybrid |
|---|---|---|
| `exit code 137` | BM25 | Hybrid |
| `8.18 breaking changes` | BM25 | Hybrid |
| `xpack.security.authc.realms configuration` | BM25 | Hybrid |
| `user can't log in` | Vector | Hybrid |

Hybrid wins all four simultaneously. **This is the retrieval engine for any RAG or agent system.**

**Next: Lab 4 — Why This Matters for Agents**
