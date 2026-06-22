# Vector → Hybrid → Do You Even Need a Model? — AIEWF 2026

**AI Engineer World's Fair 2026 — Hands-On Workshop**
Instructor: Jeff Vestal, Elastic

---

## What You'll Build

A production-grade hybrid search pipeline over an Elastic technical documentation corpus:
1. Pure vector / semantic search with Jina v5 embeddings via EIS
2. BM25 lexical search — and where it fails
3. Hybrid search: RRF and linear combination
4. A Python RAG pipeline that proves retrieval quality determines answer quality

---

## Prerequisites

- Python 3.10+
- An Elastic Serverless project (free trial: https://cloud.elastic.co/registration)
  - The project must have EIS (Elastic Inference Service) enabled — it is by default on Serverless
- An Elastic API key for your Serverless project (Kibana → Stack Management → API Keys)
- An Anthropic API key for Lab 4 synthesis (https://console.anthropic.com/)

---

## Setup

### 1. Clone this repo

```bash
git clone https://github.com/elastic/aiewf-2026-workshop
cd aiewf-2026-workshop
```

### 2. Install Python requirements

```bash
pip install elasticsearch anthropic
```

### 3. Set environment variables

```bash
export ES_ENDPOINT=https://your-project.es.us-east-1.aws.elastic.cloud
export ES_API_KEY=your_api_key_here
export ANTHROPIC_API_KEY=sk-ant-...   # only needed for Lab 4
```

### 4. Ingest the corpus

```bash
cd corpus
python ingest.py
```

Expected output: 60 documents indexed with `semantic_text` embeddings via EIS.

The ingest script will:
- Create index `aiewf-workshop-docs` with `semantic_text` field (Jina v5 via EIS)
- Bulk-index all 60 docs
- EIS generates embeddings server-side at index time — no client-side embedding code needed
- Run a quick test semantic query to verify everything worked

---

## Labs

### Labs 1–3: Dev Console Queries

Open Kibana Dev Console (your Serverless project → Kibana → Dev Tools → Console).

Copy-paste queries from the `labs/` directory. All queries use `GET aiewf-workshop-docs/_search`.

| Lab | File | What you build |
|-----|------|----------------|
| Lab 1 | [labs/lab1-vector-search.md](labs/lab1-vector-search.md) | Semantic search, EIS/Jina framing |
| Lab 2 | [labs/lab2-where-vector-breaks.md](labs/lab2-where-vector-breaks.md) | Adversarial queries, BM25 rescue, paraphrase gap |
| Lab 3 | [labs/lab3-hybrid.md](labs/lab3-hybrid.md) | RRF hybrid, linear combination, reranker |

### Lab 4: Python Notebook

Open `labs/lab4.ipynb` in Jupyter or VS Code.

```bash
jupyter notebook labs/lab4.ipynb
```

The notebook builds a full RAG pipeline: hybrid retrieve → LLM synthesize. It pre-bakes a good-context vs bad-context comparison to demonstrate that retrieval quality determines answer quality.

---

## After the Workshop

### Learn More: Elastic Documentation

- [semantic_text field type](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/semantic-text)
- [Retrievers reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers)
- [Hybrid search with semantic_text](https://www.elastic.co/docs/solutions/search/hybrid-semantic-text)
- [Elastic Inference Service (EIS)](https://www.elastic.co/docs/deploy-manage/deploy/elastic-cloud/project-settings/elastic-inference-service)
- [RRF retriever](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)

### Try It on Your Own Data

1. Create a new Elastic Serverless project
2. Modify `corpus/ingest.py` to read your own documents
3. The `semantic_text` + hybrid retriever pattern works on any text corpus

### Questions?

- Jeff Vestal: jeff.vestal@elastic.co
- Elastic Search Labs: https://search-labs.elastic.co
