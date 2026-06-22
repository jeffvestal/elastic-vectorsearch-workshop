# Expansion Plan: Vector Search Workshop — From Walkthrough to Production Deep Dive

**Event:** AIEWF 2026 (June 29) | **Duration:** 2 hours (~90 min active lab time) | **Audience:** AI engineers with RAG experience

---

## 1. Executive Summary

This expansion transitions the workshop from a basic API walkthrough into a production-grade engineering deep dive by exposing the underlying mechanics of retrieval quality, scoring, and latency. By introducing diagnostic tools (`_explain`, `_profile`), cross-encoder reranking, and explicit handling of score normalization, the curriculum directly addresses the missing abstract promise while preparing AI engineers for real-world RAG challenges. The resulting structure optimizes the 90-minute active lab window to focus on empirical observation and tuning rather than just executing pre-written queries.

---

## 2. Corpus Expansion Needed

The current 60-document corpus is insufficient for demonstrating Approximate Nearest Neighbor (ANN) tradeoffs, pagination, or the nuanced failures of vector search. 

### Expansion Plan

**Target Size:** ~250–300 documents. This is the minimum threshold where `num_candidates` tuning in ANN search begins to show measurable differences in recall versus exact kNN.

**New Trap Types:**
- **`negation` (5-10 docs):** Documents structurally identical to target queries but semantically opposite (e.g., "We do not support Elasticsearch" vs "We support Elasticsearch"). Crucial for demonstrating where cross-encoder reranking shines.
- **`access_control` (10-15 docs):** Documents tagged with specific `security_clearance` or `department` metadata to facilitate pre-filtering exercises.
- **`lexical_overlap` (10-15 docs):** Documents that share high TF-IDF token overlap with common queries but lack semantic relevance, designed to fool BM25 and require RRF/reranking to suppress.

**Implementation:** Modify the Python ingest script to generate these synthetic variations using a local LLM or hardcoded templates prior to indexing via Jina v5 embeddings.

**Why:** The current corpus lacks documents that expose:
- ANN edge cases (low `num_candidates` silently degrading recall)
- Cross-encoder necessity (semantic similarity without entailment)
- Filtering mechanics (security-aware pre-filtering)
- Pagination assumptions (large offset behavior)

---

## 3. Lab 1 Expansion — Vector Search Deep Dive (Target: 20–25 min)

This lab shifts from "how to query" to "how it executes." Attendees see the actual cost and mechanics of embedding inference, kNN traversal, and filtering.

### Exercise 1.1: Query-Time Inference Cost

**Question Answered:** How much latency does EIS (Elastic Inference Service) add to my retrieval pipeline?

**The Query:**
```json
GET aiewf-workshop-docs/_search
{
  "profile": true,
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "securing cluster traffic"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

**What to Observe:**
In the response JSON, look for the `profile` tree. It will break down:
- `inference` time: Jina v5 embedding your query text
- `search` time: HNSW traversal and vector similarity computation
- `overhead`: Deserialization, filtering, sorting

**Aha Moment:** Engineers realize vector search latency is often dominated by inference (~50-100ms), not the HNSW graph traversal (~5-10ms). This reframes the cost-benefit analysis for real-time systems.

---

### Exercise 1.2: kNN Parameters & ANN vs Exact

**Question Answered:** How does `num_candidates` affect recall and performance?

**The Query:** Run this with multiple `num_candidates` values:
```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "knn": {
      "field": "body_semantic.embedding",
      "query_vector_builder": {
        "text_embedding": {
          "model_id": "jina_v5",
          "model_text": "exit code 137 memory error"
        }
      },
      "k": 5,
      "num_candidates": 10
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

**Run three times, varying `num_candidates`:** 10, 50, 500.

**What to Observe:**
- With `num_candidates: 10`, the exact-match trap document (doc-007, exit code 137) may not appear in top 5
- With `num_candidates: 50`, it appears at rank 2–3
- With `num_candidates: 500`, it ranks #1 or #2 consistently

**Aha Moment:** `num_candidates` dictates the depth of HNSW graph search. Setting it too low silently degrades recall in larger datasets. In the 250-doc corpus, this effect is pronounced.

---

### Exercise 1.3: Pre-Filtering within Retrieval

**Question Answered:** How do I implement RBAC (Role-Based Access Control) safely in vector search?

**The Query:**
```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "knn": {
      "field": "body_semantic.embedding",
      "query_vector_builder": {
        "text_embedding": {
          "model_id": "jina_v5",
          "model_text": "security configuration"
        }
      },
      "k": 5,
      "filter": {
        "term": {
          "access_control": "public"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "access_control"]
}
```

**What to Observe:**
- Exactly 5 documents are returned (the `k` value)
- All have `"access_control": "public"`
- The filter is applied *during* graph traversal, not after

**Compare with post-filtering (what NOT to do):**
```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "knn": { ... }
  },
  "size": 5,
  "query": {
    "bool": {
      "filter": { "term": { "access_control": "public" } }
    }
  }
}
```

**What to Observe:** Now you get fewer than 5 results (possibly 2–3) because the filter is applied *after* the kNN returns 5 candidates.

**Aha Moment:** Pre-filtering (inside the retriever) ensures exactly `k` results are returned even with restrictions. Post-filtering breaks RAG context window invariants.

---

## 4. Lab 2 Expansion — Where Vector Breaks (Target: 20–25 min)

Vector search is brittle. This lab proves it empirically with diagnostic APIs.

### Exercise 2.1: Score Distributions & The Confidence Trap

**Question Answered:** Can I set a static score threshold (e.g., > 0.85) to determine if a vector result is relevant?

**The Query:**
```json
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
  "size": 10,
  "_source": ["id", "title", "trap_type"]
}
```

**What to Observe:**
- Rank 1: A docs about "memory management" (score: 0.82)
- Rank 2: A docs about "GC tuning" (score: 0.79)
- Rank 5: The actual exit-code-137 doc (score: 0.71)

All scores are in the 0.7–0.85 range. The irrelevant docs are not obviously low-confidence.

**Aha Moment:** Vector space is dense. "Low relevance" still yields high absolute scores. A naive threshold like 0.85 would incorrectly filter out the true match. Static thresholds are unreliable for RAG.

---

### Exercise 2.2: Dissecting Scores with `_explain`

**Question Answered:** Why did BM25 surface this document, but vector search missed it entirely?

**The Query (BM25):**
```json
GET aiewf-workshop-docs/_search
{
  "explain": true,
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

**The Query (Vector):**
```json
GET aiewf-workshop-docs/_search
{
  "explain": true,
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

**What to Observe:**
- BM25 `_explain`: Trace the `tf`, `idf`, and field boosts. You'll see high TF (term frequency) for "137" and very high IDF (it's a rare token). The math is: `(1 + tf) * idf * boost`.
- Vector `_explain`: The cosine similarity computation. Jina v5 compressed "exit code 137" into a general "error/failure" cluster, so topically similar but non-exact docs score equally well.

**Aha Moment:** Vector search fails on exact tokens because word embeddings compress specific signal into distributed representations. BM25 strictly rewards the rarity and co-occurrence of exact tokens.

---

### Exercise 2.3: Breaking BM25 with the Paraphrase Trap (Existing)

This exercise remains from Lab 2's Part C.

---

## 5. Lab 3 Expansion — Hybrid + Reranking (Target: 25–30 min)

Fulfilling the missing abstract promise (#5: cross-encoder reranking) and deep-diving into normalization mechanics.

### Exercise 3.1: Score Normalization (MinMax Demystified)

**Question Answered:** Why can't I just add a BM25 score to a Cosine Similarity score?

**The Query (Raw Scores):**
```json
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
  "size": 3,
  "_source": ["id", "title"]
}
```

**What to Observe:** BM25 scores are unbounded. The top doc scores 12.5.

**Now run semantic:**
```json
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
  "size": 3,
  "_source": ["id", "title"]
}
```

**What to Observe:** Cosine similarity is bounded 0–1. The top doc scores 0.92.

**Now a naive linear combo (hypothetical, for illustration):** If you set `weight_bm25 = 0.5` and `weight_semantic = 0.5` without normalization:
- Naive score = 0.5 * 12.5 + 0.5 * 0.92 = 6.71
- The semantic component is effectively drowned out.

**With MinMax normalization (Demo with the linear retriever):**
```json
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

**What to Observe:**
- Each sub-retriever's scores are scaled to [0, 1]
- The final combined score respects both signals equally

**Aha Moment:** Linear combination requires normalization because score ranges differ. RRF avoids this entirely by working on *ranks*, not raw scores.

---

### Exercise 3.2: RRF Tuning Math

**Question Answered:** How does `rank_constant` shift document prioritization?

**The Query (rank_constant: 60 — default):**
```json
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
  "_source": ["id", "title", "trap_type"]
}
```

**Now change to rank_constant: 10:**
Re-run the query with `"rank_constant": 10` in the same RRF block.

**What to Observe:**
- With `rank_constant: 60`, both the semantic and BM25 sub-retrievers contribute balanced weight. Documents that appear in top 10 of either are competitive.
- With `rank_constant: 10`, documents that rank outside the top 3 in both sub-retrievers drop sharply. The penalty for being at rank 5 is much harsher.

**RRF Formula:** `score = 1 / (rank_constant + rank)`. With constant=60, rank 5 contributes 1/65 ≈ 0.015. With constant=10, it contributes 1/15 ≈ 0.067.

**Aha Moment:** `rank_constant` controls the "early-out" curve. Low constants favor fusion of top hits; high constants allow deeper tail participation. For RAG (where top 5 matters), rank_constant=60 is reasonable. For strict top-3 prioritization, use 10–20.

---

### Exercise 3.3: Cross-Encoder Reranking (The Missing Promise)

**Question Answered:** How do I fix the `negation` trap where bi-encoders (vectors) fail to distinguish entailment?

**The Negation Trap:** Query: "Does Elasticsearch have cross-cluster replication?" Two documents both score high for semantic similarity:
- **Relevant:** "Cross-cluster replication (CCR) enables asynchronous replication of indices across clusters..."
- **Trap:** "Elasticsearch does NOT have cross-cluster replication in version 7.x; use snapshot-restore instead..."

Both are semantically about CCR, but one is actually negative. A bi-encoder can't distinguish intent.

**The Query (Pre-Reranking Hybrid):**
```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": { ... }
  },
  "size": 5,
  "_source": ["id", "title", "body"]
}
```

**What to Observe:** The negation trap doc ranks #1 or #2.

**The Query (Post-Reranking with Cross-Encoder):**
```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "text_similarity_reranker": {
      "retriever": {
        "rrf": {
          "retrievers": [ ... ]
        }
      },
      "field": "body",
      "inference_id": ".elastic-text-similarity-reranker",
      "inference_text": "Does Elasticsearch have cross-cluster replication?",
      "window_size": 10
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

**What to Observe:** The negation trap document drops to rank 4–5. The true CCR documentation lands at #1.

**Aha Moment:** Cross-encoders score query-document *pairs* for true relevance/entailment, not just topical similarity. Reranking is the necessary final step for high-precision RAG systems.

---

## 6. Lab 4 — RAG Pipeline (Target: 15–20 min)

The notebook is solid. These additions tie the previous labs' diagnostics back to the final LLM answer quality.

### Addition 1: Retrieval Latency Profiling

**New Cell (before synthesis):**
```python
import time
import json

# Run hybrid search with profiling
start = time.time()
response = es.search(
    index='aiewf-workshop-docs',
    body={
        "retriever": { ... },  # Lab 3 hybrid RRF
        "size": 5,
        "_source": ["id", "title", "body"]
    }
)
elapsed = time.time() - start

print(f'Total retrieval time: {elapsed * 1000:.1f} ms')

# Break down latency (if _profile is available)
docs = response['hits']['hits']
print(f'Retrieved {len(docs)} docs')
for doc in docs:
    print(f"  [{doc['_id']}] {doc['_source']['title']}")
```

**Aha:** Engineers see that inference time dominates the 90-150ms total retrieval latency.

### Addition 2: Context Contamination & Reranking Impact

**New Cells (for comparison):**

**Cell 7b (Bad Context — No Reranking):**
Manually inject a `lexical_overlap` trap document into the context (e.g., a document about ILM that happens to mention "cluster" and "scaling"):

```python
# Simulate bad retrieval (no reranking)
contaminated_context = [
    trap_doc_lexical_overlap,  # This shouldn't be in top 5, but is due to BM25 overlap
    *docs[1:4]  # real docs
]

question = "How do I scale my cluster?"
bad_answer = synthesize(contaminated_context, question)
print("--- Answer with contaminated context ---")
print(bad_answer)
```

**Cell 7c (Good Context — With Reranking):**
Apply `text_similarity_reranker` to filter out the trap:

```python
# Same question, but with reranking
response = es.search(
    index='aiewf-workshop-docs',
    body={
        "retriever": {
            "text_similarity_reranker": {
                "retriever": { ... },
                "inference_text": "How do I scale my cluster?"
                # ... rest of reranker config
            }
        }
    }
)
clean_docs = [hit['_source'] for hit in response['hits']['hits']]
good_answer = synthesize(clean_docs, question)
print("--- Answer with reranked context ---")
print(good_answer)
```

**Aha:** Attendees see how reranking removes false positives, preventing hallucination in the LLM response.

---

## 7. Optional Bonus Content

For fast learners who finish the 90-minute track early.

### Bonus 1: Field Boosting Impact

Modify the BM25 query inside any hybrid retriever to experiment with field weights:

```json
{
  "multi_match": {
    "query": "kNN search",
    "fields": ["title^5", "body^1"],
    "type": "best_fields"
  }
}
```

Then swap to `title^2` and observe how top ranks shift. Use `_explain` to show the multiplier in action.

### Bonus 2: Production Pagination (`search_after`)

Explain why `from: 10000` throws an error in Elasticsearch. Then demonstrate `search_after`:

```json
GET aiewf-workshop-docs/_search
{
  "retriever": { ... },
  "size": 5,
  "sort": [
    { "_score": { "order": "desc" } },
    { "_id": { "order": "asc" } }
  ]
}

# Extract the sort values from the last hit, then use them in the next query:
GET aiewf-workshop-docs/_search
{
  "retriever": { ... },
  "size": 5,
  "search_after": [0.92, "doc-042"],  // sort values from previous last hit
  "sort": [ ... ]
}
```

This is a production concern AI engineers hit immediately when building paginated RAG interfaces.

---

## 8. Implementation Estimate

### Corpus Expansion
- **Scope:** Generate ~190 new synthetic documents covering `negation`, `access_control`, and `lexical_overlap` trap types.
- **Method:** Use templates + Jina v5 embeddings; extend `corpus/ingest.py` to include these new docs.
- **Effort:** 3–4 hours (data generation, validation, ingest testing).

### Assignment Rewrites
- **`01-vector-search/assignment.md`:** Expand from 98 to ~200 lines (add Exercises 1.1–1.3)
- **`02-where-vector-breaks/assignment.md`:** Expand from 144 to ~220 lines (add Exercises 2.1–2.2)
- **`03-hybrid-search/assignment.md`:** Expand from 143 to ~280 lines (add Exercises 3.1–3.3 with full DSL)
- **`04-why-it-matters/assignment.md`:** +30 lines for reranking context + latency profiling guidance
- **Effort:** 4–6 hours (writing, DSL testing, wordsmithing).

### Notebook Additions
- **`lab4.ipynb`:** Add cells 7b (contamination demo), 7c (reranking demo), latency profiling instrumentation
- **Effort:** 2–3 hours (implementation, testing against ES 9.x Serverless).

### Total
**~1.5 days of engineering time** to implement, test, and dry-run against live ES 9.x Serverless. Plan for a final 30-min validation pass 1 day before the workshop.

---

## Success Criteria

- Attendees can explain why vector search fails on exact tokens and why BM25 fails on paraphrases
- Attendees understand the mathematical basis of score normalization and RRF tuning
- Attendees see cross-encoder reranking in action on a negation trap
- Attendees can articulate how retrieval quality bounds RAG answer quality
- All labs execute end-to-end within the 90-minute window with slack for Q&A

