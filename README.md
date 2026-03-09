# Bob

Your AI agent. A production-ready chatbot demonstrating:
- **Conversational AI** with persistent session memory
- **RAG** (Retrieval-Augmented Generation) with ChromaDB
- **Agentic tool use** via Strands Agents
- **Provider abstraction**: Amazon Bedrock or any local OpenAI-compatible model (LM Studio, Ollama, etc.)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      FastAPI  (api/)                          │
│                                                               │
│  /api/v1/chat   ──► ConversationMemory ──► LLM Provider      │
│  /api/v1/rag    ──► ChromaDB ──────────► LLM Provider        │
│  /api/v1/agent  ──► Strands Agent ─────► LLM Provider        │
└──────────────────────┬───────────────────────────────────────┘
                       │
         ┌─────────────▼──────────────┐
         │     LLM Provider (core/)    │
         │  ┌──────────┐ ┌──────────┐ │
         │  │ Bedrock  │ │  Local   │ │
         │  │ (boto3)  │ │(OpenAI)  │ │
         │  └──────────┘ └──────────┘ │
         └────────────────────────────┘
```

---

## Quick Start (Local — no Docker)

### 1. Clone and enter the project

```bash
cd bob
```

### 2. Create and activate a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env — the defaults already point to the local LM Studio model
```

### 5. Start LM Studio

- Open **LM Studio** → Load any model (e.g. Qwen3-30B, Llama 3, etc.)
- Go to **Local Server** tab → Start server (default: `http://localhost:1234`)
- Update `LOCAL_MODEL_BASE_URL` in `.env` if your port differs:

```env
LOCAL_MODEL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL_NAME=<exact-model-name-from-lm-studio>
```

> **Tip:** The model name must match what LM Studio shows in its server info panel.

### 6. Run the API

```bash
uvicorn api.main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive Swagger UI.

---

## API Endpoints

All endpoints require the `X-API-Key` header (default: `dev-secret-key-change-in-prod`).

### Chat

#### Send a message

```bash
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -d '{"message": "Hello! What can you do?"}'
```

#### Continue a conversation

```bash
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -d '{"message": "Tell me more.", "session_id": "<session_id_from_above>"}'
```

#### Stream a response (SSE)

```bash
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -d '{"message": "Write a short poem.", "stream": true}'
```

#### Get conversation history

```bash
curl http://localhost:8000/api/v1/chat/<session_id>/history \
  -H "X-API-Key: dev-secret-key-change-in-prod"
```

#### Clear a session

```bash
curl -X DELETE http://localhost:8000/api/v1/chat/<session_id> \
  -H "X-API-Key: dev-secret-key-change-in-prod"
```

---

### RAG

#### Ingest a document

```bash
curl -X POST http://localhost:8000/api/v1/rag/ingest \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -F "file=@data/sample_docs/company_overview.md"
```

#### Ingest all sample documents at once (ETL script)

```bash
python -m pipelines.etl data/sample_docs/
```

#### Query the knowledge base

```bash
curl -X POST http://localhost:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -d '{"query": "What products does NovaTech AI offer?"}'
```

#### List ingested documents

```bash
curl http://localhost:8000/api/v1/rag/documents \
  -H "X-API-Key: dev-secret-key-change-in-prod"
```

---

### Agent

#### Run an agent task

```bash
curl -X POST http://localhost:8000/api/v1/agent/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -d '{"task": "What is 15% of 4200? Also, what time is it now?"}'
```

#### Check run status

```bash
curl http://localhost:8000/api/v1/agent/<run_id>/status \
  -H "X-API-Key: dev-secret-key-change-in-prod"
```

---

## Switching Between Providers

### Local (LM Studio — default)

```env
LLM_PROVIDER=local
LOCAL_MODEL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL_NAME=lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF
LOCAL_MODEL_API_KEY=not-needed
```

### Amazon Bedrock

```env
LLM_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

> Make sure your IAM user/role has `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` permissions.

---

## Ingesting Documents

```bash
# Single file via API
curl -X POST http://localhost:8000/api/v1/rag/ingest \
  -H "X-API-Key: dev-secret-key-change-in-prod" \
  -F "file=@/path/to/your/document.pdf"

# Batch ingest an entire directory
python -m pipelines.etl /path/to/docs/ --chunk-size 512 --chunk-overlap 50

# Dry run (discover files without ingesting)
python -m pipelines.etl /path/to/docs/ --dry-run
```

---

## Running Tests

```bash
pytest
```

Run with verbose output:

```bash
pytest -v --tb=short
```

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `local` | LLM backend: `bedrock` or `local` |
| `AWS_ACCESS_KEY_ID` | — | AWS access key (Bedrock only) |
| `AWS_SECRET_ACCESS_KEY` | — | AWS secret key (Bedrock only) |
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region (Bedrock only) |
| `LOCAL_MODEL_BASE_URL` | `http://model-lab.webdirect.ro/v1` | OpenAI-compatible server URL |
| `LOCAL_MODEL_NAME` | `qwen3-30b` | Model name at the local server |
| `LOCAL_MODEL_API_KEY` | `not-needed` | API key for local server |
| `API_KEY` | `dev-secret-key-change-in-prod` | X-API-Key value for auth |
| `SYSTEM_PROMPT` | `You are a helpful AI assistant.` | Default system prompt |
| `CHROMA_HOST` | `localhost` | ChromaDB host |
| `CHROMA_PORT` | `8001` | ChromaDB port |
| `CHROMA_USE_HTTP` | `false` | Use HTTP client vs. local persistence |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins |

---

## Project Structure

```
bob/
├── api/
│   ├── main.py              # FastAPI app, middleware, routers
│   ├── dependencies.py      # DI providers (LLM, memory, RAG, agent)
│   └── routes/
│       ├── chat.py          # Conversational chat with memory + SSE
│       ├── rag.py           # RAG ingestion and querying
│       └── agent.py         # Strands agent task runner
├── core/
│   ├── llm/
│   │   ├── base.py          # Abstract BaseLLMProvider
│   │   ├── bedrock.py       # Amazon Bedrock provider (boto3)
│   │   └── local.py         # Local/OpenAI-compatible provider
│   ├── memory/
│   │   └── conversation.py  # In-memory session store
│   ├── rag/
│   │   ├── ingestion.py     # Document ingestion pipeline
│   │   ├── retriever.py     # ChromaDB wrapper
│   │   └── pipeline.py      # RAG query pipeline
│   └── agent/
│       ├── orchestrator.py  # Strands agent orchestrator + run history
│       └── tools.py         # Agent tools: calculator, time, RAG lookup, summarize
├── pipelines/
│   └── etl.py               # Batch document ingestion CLI
├── infrastructure/
│   └── Dockerfile           # Production Docker image
├── tests/
│   ├── test_chat.py
│   ├── test_rag.py
│   └── test_agent.py
├── data/
│   └── sample_docs/         # Sample markdown documents for demo
│       ├── company_overview.md
│       ├── product_faq.md
│       └── technical_docs.md
├── .env.example
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Built With

| Technology | Role |
|---|---|
| **FastAPI** | Async REST API framework |
| **Pydantic v2** | Request/response validation and schemas |
| **Strands Agents** | Agent orchestration and tool use |
| **LangChain** | Document loading, splitting, RAG pipeline |
| **ChromaDB** | Local vector store for embeddings |
| **Amazon Bedrock** | Managed LLM inference (Claude, Titan) |
| **openai (SDK)** | OpenAI-compatible client for local models |
| **sentence-transformers** | Local embedding fallback |
| **boto3** | AWS SDK for Bedrock and DynamoDB |
| **uvicorn** | ASGI server |
| **pytest** | Test framework |
| **python-dotenv** | Environment variable management |
# bob
