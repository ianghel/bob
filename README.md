# Bob

An AI agent platform with multi-tenant authentication, conversational memory, RAG (Retrieval-Augmented Generation), and agentic tool use.

## Features

- **Conversational AI** with persistent session memory and SSE streaming
- **RAG** pipeline with ChromaDB vector store for document-grounded answers
- **Agentic tool use** via Strands Agents (calculator, time, RAG lookup, summarize)
- **Multi-tenant auth** with JWT login, user registration, admin approval, and API tokens
- **Provider abstraction**: Amazon Bedrock or any OpenAI-compatible server (LM Studio, Ollama, vLLM)
- **React frontend** (Vite + TypeScript + Tailwind)
- **AWS deployment** via CloudFormation + automated deploy script

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     FastAPI  (api/)                           │
│                                                              │
│  /api/v1/auth    ──► JWT login / register / approval         │
│  /api/v1/chat    ──► ConversationMemory ──► LLM Provider     │
│  /api/v1/rag     ──► ChromaDB ──────────► LLM Provider       │
│  /api/v1/agent   ──► Strands Agent ─────► LLM Provider       │
│  /api/v1/tokens  ──► API token management                    │
│  /api/v1/tenants ──► Tenant administration                   │
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

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend)
- MariaDB or MySQL (for user/tenant storage)
- An OpenAI-compatible model server (LM Studio, Ollama, etc.) **or** AWS Bedrock access

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd bob
```

### 2. Create a Python virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up the database

Create a MariaDB/MySQL database and user:

```sql
CREATE DATABASE bob CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'bob'@'localhost' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON bob.* TO 'bob'@'localhost';
FLUSH PRIVILEGES;
```

Run migrations:

```bash
alembic upgrade head
```

### 5. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

Key settings in `.env`:

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | `local` (default) or `bedrock` |
| `LOCAL_MODEL_BASE_URL` | Your model server URL (e.g. `http://localhost:1234/v1`) |
| `LOCAL_MODEL_NAME` | Model name as shown by your server |
| `LOCAL_MODEL_API_KEY` | API key for the model server (or `not-needed`) |
| `API_KEY` | Static API key for backward-compatible endpoints |
| `DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` | Database connection |
| `JWT_SECRET` | Secret for signing JWT tokens (change in production!) |
| `MAIL_*` | SMTP settings for user approval emails |

### 6. Start a model server

**LM Studio:**
- Load a model (e.g. Qwen, Llama, Mistral)
- Go to **Local Server** tab and start the server
- Set `LOCAL_MODEL_BASE_URL` and `LOCAL_MODEL_NAME` in `.env`

**Ollama:**
```bash
ollama serve
# LOCAL_MODEL_BASE_URL=http://localhost:11434/v1
```

### 7. Run the API

```bash
uvicorn api.main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) for the Swagger UI.

### 8. Run the frontend (optional)

```bash
cd bob-ui
npm install
npm run dev
```

Opens at [http://localhost:5173](http://localhost:5173).

---

## API Endpoints

### Authentication

```bash
# Register a new user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret", "name": "Alice"}'

# Login (returns JWT token)
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "secret"}'

# Get current user profile
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <token>"
```

New users require admin approval before they can access the API. The first registered user is auto-approved as admin.

### Chat

All authenticated endpoints require `Authorization: Bearer <token>` header.

```bash
# Send a message
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "Hello! What can you do?"}'

# Continue a conversation
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "Tell me more.", "session_id": "<session_id>"}'

# Stream a response (SSE)
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message": "Write a short poem.", "stream": true}'

# List sessions
curl http://localhost:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer <token>"

# Get conversation history
curl http://localhost:8000/api/v1/chat/<session_id>/history \
  -H "Authorization: Bearer <token>"
```

### RAG (Knowledge Base)

```bash
# Ingest a document
curl -X POST http://localhost:8000/api/v1/rag/ingest \
  -H "Authorization: Bearer <token>" \
  -F "file=@path/to/document.pdf"

# Query the knowledge base
curl -X POST http://localhost:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"query": "What does our company policy say about remote work?"}'

# List ingested documents
curl http://localhost:8000/api/v1/rag/documents \
  -H "Authorization: Bearer <token>"

# Batch ingest a directory
python -m pipelines.etl /path/to/docs/ --chunk-size 512 --chunk-overlap 50
```

### Agent

```bash
# Run an agent task (uses tools: calculator, time, RAG lookup, summarize)
curl -X POST http://localhost:8000/api/v1/agent/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"task": "What is 15% of 4200? Also, what time is it now?"}'

# Check run status
curl http://localhost:8000/api/v1/agent/<run_id>/status \
  -H "Authorization: Bearer <token>"
```

### API Tokens

For programmatic access without JWT login:

```bash
# Create an API token
curl -X POST http://localhost:8000/api/v1/tokens/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"name": "my-script"}'
# Returns a bob_xxx... token — save it, it's shown only once

# Use the token (pass as Bearer token)
curl http://localhost:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer bob_xxx..."
```

---

## Switching LLM Providers

### Local (LM Studio / Ollama — default)

```env
LLM_PROVIDER=local
LOCAL_MODEL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL_NAME=your-model-name
LOCAL_MODEL_API_KEY=not-needed
```

### Amazon Bedrock

```env
LLM_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

Your IAM user/role needs `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` permissions.

---

## Running Tests

```bash
pytest
pytest -v --tb=short
```

---

## Deployment (AWS)

Bob includes a CloudFormation template and deploy script for single-instance AWS deployment (EC2 + MariaDB + nginx + CloudFront).

```bash
# 1. Configure deployment
cp infra/scripts/deploy.env.example infra/scripts/deploy.env
# Edit deploy.env with your AWS and app settings

# 2. Deploy infrastructure + code
./deploy --infra

# 3. Subsequent code-only deploys
./deploy
```

See `infra/scripts/deploy.env.example` for all available configuration options.

---

## Project Structure

```
bob/
├── api/
│   ├── main.py              # FastAPI app, middleware, routers
│   ├── dependencies.py      # DI providers (LLM, auth, RAG, agent)
│   └── routes/
│       ├── auth.py           # JWT login, register, user management
│       ├── chat.py           # Conversational chat with memory + SSE
│       ├── rag.py            # RAG ingestion and querying
│       ├── agent.py          # Strands agent task runner
│       ├── tenants.py        # Tenant administration
│       └── tokens.py         # API token CRUD
├── core/
│   ├── auth/
│   │   ├── service.py        # User/auth business logic
│   │   ├── jwt.py            # JWT token encode/decode
│   │   ├── api_tokens.py     # API token hashing & validation
│   │   └── email.py          # SMTP notifications (approval emails)
│   ├── database/
│   │   ├── engine.py         # Async SQLAlchemy engine
│   │   └── models.py         # ORM models (User, Tenant, ApiToken, etc.)
│   ├── llm/
│   │   ├── base.py           # Abstract BaseLLMProvider
│   │   ├── bedrock.py        # Amazon Bedrock provider (boto3)
│   │   └── local.py          # OpenAI-compatible provider
│   ├── memory/
│   │   └── conversation.py   # In-memory session store
│   ├── rag/
│   │   ├── ingestion.py      # Document ingestion pipeline
│   │   ├── retriever.py      # ChromaDB wrapper
│   │   └── pipeline.py       # RAG query pipeline
│   ├── agent/
│   │   ├── orchestrator.py   # Strands agent orchestrator
│   │   └── tools.py          # Agent tools
│   └── tenant/
│       └── service.py        # Tenant provisioning
├── bob-ui/                    # React frontend (Vite + TypeScript + Tailwind)
│   ├── src/
│   │   ├── components/        # Chat, RAG, Agent, Auth, Settings panels
│   │   ├── api/client.ts      # Typed API client
│   │   └── store/             # Auth & settings state
│   └── package.json
├── alembic/                   # Database migrations
│   └── versions/
├── pipelines/
│   └── etl.py                 # Batch document ingestion CLI
├── infra/
│   ├── cloudformation/        # AWS CloudFormation templates
│   └── scripts/               # Deploy scripts & config
├── tests/
├── .env.example
├── alembic.ini
├── requirements.txt
├── requirements-prod.txt
├── pytest.ini
└── README.md
```

---

## Built With

| Technology | Role |
|---|---|
| **FastAPI** | Async REST API framework |
| **SQLAlchemy 2** | Async ORM for user/tenant data |
| **Alembic** | Database migrations |
| **Strands Agents** | Agent orchestration and tool use |
| **LangChain** | Document loading, splitting, embeddings |
| **ChromaDB** | Local vector store |
| **Amazon Bedrock** | Managed LLM inference (Claude, Titan) |
| **openai SDK** | OpenAI-compatible client for local models |
| **React + Vite** | Frontend SPA |
| **Tailwind CSS** | UI styling |
| **boto3** | AWS SDK |
| **uvicorn** | ASGI server |
| **pytest** | Test framework |

---

## License

This project is licensed under the [MIT License](LICENSE).
