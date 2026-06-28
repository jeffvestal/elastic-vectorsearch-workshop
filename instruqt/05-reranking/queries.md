# Lab 5 (Bonus) — Dev Console Snippets

Reranking from the Dev Console. The notebook (`lab5-reranking.ipynb`) is the main path; these
are the instructor crib / Dev Console equivalents. Both rerank endpoints are provisioned on the
project: `.jina-reranker-v2-base-multilingual` (pointwise cross-encoder) and `.jina-reranker-v3`
(listwise).

---

## Snippet 1 — List the rerank endpoints

```
GET _inference/rerank/_all
```

**What to look for:** `.jina-reranker-v2-base-multilingual` and `.jina-reranker-v3`, each with
`"service": "elastic"` and `"task_type": "rerank"`. (Cmd/Ctrl-F `rerank` if the list is long.)

---

## Snippet 2 — Call the reranker DIRECTLY (the rawest form)

Send a query + a list of candidate texts; get back each one's relevance score, re-sorted.

```
POST _inference/rerank/.jina-reranker-v3
{
  "query": "how do I encrypt traffic between cluster nodes",
  "input": [
    "TLS encryption for cluster communications. Configure transport-layer TLS so nodes authenticate and encrypt traffic between each other.",
    "Set up security in self-managed Elasticsearch deployments. Enable the security features, set passwords, and configure roles.",
    "Container exit codes when a process is killed. Exit code 137 indicates the process received SIGKILL, often from an out-of-memory condition."
  ]
}
```

**Expected:** a `rerank` array sorted by `relevance_score`, with `index: 0` (the TLS text) on top.
Swap the `inference_id` to `.jina-reranker-v2-base-multilingual` to see the **pointwise** scores —
on a clean 3-item set the order usually matches; the listwise edge shows on larger, overlapping sets.

---

## Snippet 3 — Production path: `text_similarity_reranker` (recall → precision in one query)

Wrap the Lab 3 RRF hybrid retriever; the reranker re-scores the top `rank_window_size` candidates.

```
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
      "inference_id": ".jina-reranker-v3",
      "inference_text": "how do I secure traffic between nodes",
      "rank_window_size": 50
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

**Expected:** the TLS / cluster-comms doc (doc-010) at #1, now scored by the reranker rather than
RRF. `inference_text` is REQUIRED — the reranker needs the query string. Swap `inference_id` to
`.jina-reranker-v2-base-multilingual` to compare pointwise vs listwise.

> **Reality check (62-doc corpus):** RRF already nails #1 on most queries, so reranking has little
> room to move things here — this is a MECHANICS demo. The payoff is real when stage 1 returns
> hundreds of plausible, overlapping candidates.
