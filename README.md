# incident-summarizer

## File Structure

```
incident-summarizer/
├── app/
│   ├── api/            # FastAPI route handlers (HTTP layer only, no business logic)
│   ├── core/           # Config, settings, constants, loaded once at startup
│   ├── db/             # DB connection, pgvector schema, query helpers
│   ├── indexing/       # Embedding + ingestion pipeline (runs offline)
│   ├── retrieval/      # Vector similarity search logic
│   └── summarizer/     # Prompt construction + Claude API calls
├── data/
│   ├── incidents/      # Raw synthetic incident logs (.txt or .json)
│   └── runbooks/       # Markdown runbooks
├── scripts/            # One-off CLI scripts: seed DB, run indexing, etc.
├── tests/
├── infra/              # Terraform or CloudFormation
└── .github/workflows/  # CI/CD
```

The `indexing/` pipeline runs offline at ingest time, it's not in the request path. The `retrieval/` and `summarizer/` modules run at query time. Keeping them separate means you can re-index without touching the API, and you can swap the LLM without touching retrieval.

## Layer 1: The Indexing Pipeline

This is what runs when you load new data. The flow is:

```
Raw file → Chunker → Voyage-3 embedding → pgvector row
```

## Step 1: Chunking strategy
__Incident logs:__ Each log is one chunk. They're already atomic (one event, one embedding). Metadata you attach: `source_file`, `chunk_type: "incident"`, `timestamp`, `severity` if parseable.

__Runbooks:__ Structure-aware chunking on markdown headers. You split on `##` and `###` headings, keep the heading text as part of the chunk (so the embedding captures the topic), and attach metadata: `source_file`, `chunk_type: "runbook"`, section (the heading text), parent_section if it's a sub-heading.

### "Why not just embed the whole runbook?"
Because a 4,000-token runbook embedded as one vector loses granularity. If someone asks about the rollback procedure specifically, you want to retrieve that section, not the whole doc and hope the LLM finds it.   
Smaller, focused chunks = more precise retrieval.

## Step 2: Embedding with Voyage-3
Voyage-3 is a retrieval-optimized model. You call it with your chunk text and get back a 1024-dimensional float vector. One API call per chunk (or batch them, Voyage supports batching).

Why Voyage over OpenAI embeddings? Voyage-3 consistently benchmarks higher on retrieval tasks (MTEB leaderboard). For a healthcare security context, retrieval precision matters, you don't want to surface the wrong runbook.

## Step 3: Storing in pgvector
The PostgreSQL table looks roughly like this:

```
CREATE TABLE chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL,
    embedding   vector(1024),        -- matches Voyage-3 output dim
    source_file TEXT,
    chunk_type  TEXT,                -- 'incident' | 'runbook'
    section     TEXT,                -- runbook section heading
    metadata    JSONB,               -- flexible bag for extras
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```


### "Why IVFFlat and not HNSW?"
IVFFlat is good for smaller datasets (under ~1M rows) and has lower memory overhead. HNSW has better recall at scale but uses significantly more RAM. For a demo/MVP with hundreds of chunks, IVFFlat is the right call. I'll revisit this at scale.

### Why cosine similarity and not L2? 
Embeddings from Voyage-3 are normalized. Cosine similarity is the right distance metric for semantic similarity on normalized vectors.

## The Mental Model

1. User submits a query
2. Query comes in and is sanitized and validated at the API layer
3. Query is embedded with Voyage-3 (same model as index)
4. pgvector does a cosine similarity search against the chunks table and returns top-k
5. These chunks become context that is injected into a system prompt to Claude
6. Claude returns a summary grounded in retrieved content
7. Full request/response is logged for auditability (important for healthcare in case of HIPAA audit trials)