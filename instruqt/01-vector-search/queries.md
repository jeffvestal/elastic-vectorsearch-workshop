# Lab 1 — Dev Console Snippets

Copy-paste these into Kibana Dev Console. Run them in order.

---

## Snippet 1 — GET Mapping (see the semantic_text field)

```
GET aiewf-workshop-docs/_mapping
```

**What to look for:**
- `body_semantic.type` = `"semantic_text"`
- `body_semantic.inference_id` = `".jina-embeddings-v5-text-small"`
- `body.type` = `"text"` (plain BM25 field — used in Labs 2 & 3)

---

## Snippet 2 — GET Inference Endpoint Config (EIS is real infrastructure)

**2a — Discovery: list only the embedding endpoints.** Scopes to `text_embedding` so you don't have to scan past rerankers and LLMs. (Tip for attendees: Cmd/Ctrl-F `jina` in the output pane to jump to it.)

```
GET _inference/text_embedding/_all
```

**2b — Fetch the specific endpoint config** once you've spotted it by name:

```
GET _inference/text_embedding/.jina-embeddings-v5-text-small
```

**What to look for:**
- `service`: `"elastic"` — this is EIS, not an external API call
- `task_type`: `"text_embedding"`
- The model id and any rate_limit info

This endpoint is called automatically every time you index a doc or run a `semantic` query.

---

## Snippet 3 — Semantic Query: "securing cluster traffic"

The "wow" query — asks about securing traffic, gets the TLS page.

```
GET aiewf-workshop-docs/_search
{
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
  "_source": ["id", "title", "summary"]
}
```

**Expected result:** top hit should be the TLS/SSL cluster communications page. The word "TLS" does not appear in the query. Semantic matching found it anyway.

---

## Snippet 4 — Semantic Query: "how do I back up my cluster data"

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "how do I back up my cluster data"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

**Expected result:** snapshot and restore documentation. The word "backup" may not appear in the doc title — but "snapshot" and "data backup" are semantically equivalent to Jina v5.

---

## Snippet 5 — Semantic Query: "users can't connect to Kibana"

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "users can't connect to Kibana"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

**Expected result:** Kibana configuration/network access pages. "Can't connect" maps semantically to "connection refused", "proxy", "network access", "port" — all concepts in Kibana setup docs.

---

## Bonus — Inspect a Specific Doc

```
GET aiewf-workshop-docs/_doc/doc-010
```

See the full indexed doc including `body_semantic` — notice it looks like a nested object with chunks and embeddings (that's how `semantic_text` stores the data internally).
