# Bob

An AI agent platform with multi-tenant authentication, conversational memory, RAG (Retrieval-Augmented Generation), and agentic tool use.

## Features

- **Conversational AI** with persistent session memory and SSE streaming
- **Web Search** — Bob searches the internet (Google via Serper.dev) for up-to-date info, compares prices, and recommends products
- **File Upload in Chat** — upload PDF, TXT, MD, DOCX files directly from chat; files are auto-ingested into Bob's memory (knowledge base) and Bob summarizes the content
- **Voice Input** — record voice messages from the chat UI; audio is transcribed via **Whisper** or **AWS Transcribe** with auto language detection or manual language selection (RO, EN, DE, FR, ES)
- **Text-to-Speech** — multiple TTS providers with automatic language routing:
  - **Kokoro TTS** — GPU-accelerated, self-hosted; 26 voices (male/female, US/British English); chunked playback
  - **AWS Polly** — cloud-based TTS with generative voices (Ruth, Danielle, etc.)
  - **Piper TTS** — local, natural-sounding Romanian voice (`ro_RO-mihai-medium`); auto-routed when `lang=ro`
- **URL Fetching** — Bob can fetch and analyze web pages, saving them to his memory
- **Email Integration** — multi-account support:
  - **Gmail OAuth2** — each user connects their own Gmail account from the UI
  - **IMAP/SMTP** — connect any email provider (WorkMail, Outlook, custom servers)
  - Bob syncs inbox and sent emails, triages them with LLM (urgency, category, action, reply draft), and displays everything in an Email dashboard
  - **Email indexing in ChromaDB** — email content is semantically searchable via RAG
  - **Contact list** — auto-extracted from synced emails
- **Email in Chat** — ask Bob "ce emailuri am primit azi?", "trimite un email lui X", or "rezumat emailuri" and he uses tool calls (`send_email`, `search_emails`, `get_email_summary`) to interact with your email
- **Background Email Sync** — per-user async sync triggered on login, then every 5 minutes; keeps the 50 most recent emails per user
- **RAG** pipeline with ChromaDB vector store for document-grounded answers
- **Agentic tool use** via Strands Agents (calculator, time, RAG lookup, summarize, email tools)
- **Usage Limits** — configurable monthly spending cap ($10/month default) for Bedrock LLM calls; tracks token usage per call, resets automatically each calendar month
- **Multi-tenant auth** with JWT login, user registration, email verification, and API tokens
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
│  /api/v1/chat    ──► ConversationMemory ──► LLM + Web Tools   │
│  /api/v1/chat/transcribe ──► Whisper / AWS Transcribe          │
│  /api/v1/chat/speak      ──► Kokoro / Polly / Piper TTS      │
│  /api/v1/email   ──► Gmail OAuth ──► Sync + LLM triage       │
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
| `SERPER_API_KEY` | API key from [serper.dev](https://serper.dev) for Google search |
| `WHISPER_BASE_URL` | Whisper-compatible STT server URL (e.g. `https://your-server/v1`) |
| `WHISPER_API_KEY` | API key for the Whisper server |
| `TTS_BASE_URL` | Kokoro TTS (or OpenAI-compatible) server URL (e.g. `https://your-server/v1`) |
| `TTS_API_KEY` | API key for the TTS server |
| `TTS_MODEL` | TTS model name (default: `kokoro`) |
| `TTS_VOICE` | Default TTS voice (default: `af_heart`) |
| `PIPER_BASE_URL` | Piper TTS server URL (for Romanian voice) |
| `PIPER_API_KEY` | API key for Piper TTS |
| `PIPER_VOICE` | Piper voice (default: `ro_RO-mihai-medium`) |
| `STT_PROVIDER` | `whisper` (default) or `transcribe` (AWS Transcribe) |
| `TTS_PROVIDER` | `kokoro` (default), `polly`, or `piper` |
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID (for Gmail integration) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL (e.g. `https://your-domain/api/v1/email/callback/gmail`) |
| `BASE_URL` | Public app URL (e.g. `https://your-domain`) |
| `MAIL_*` | SMTP settings for user approval emails |
| `USAGE_LIMIT_ENABLED` | Enable monthly spending cap (default: `true`) |
| `USAGE_LIMIT_MONTHLY_USD` | Monthly limit in USD (default: `10.00`) |

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

New users must verify their email address before they can access the API. The first registered user is auto-approved as admin.

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

# Upload a file to chat (auto-saved to Bob's memory)
curl -X POST http://localhost:8000/api/v1/chat/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf" \
  -F "message=What's in this file?"

# Fetch a URL into the knowledge base
curl -X POST http://localhost:8000/api/v1/chat/fetch-url \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"url": "https://example.com/article"}'

# Transcribe audio (Whisper or AWS Transcribe, auto-detect language)
curl -X POST http://localhost:8000/api/v1/chat/transcribe \
  -H "Authorization: Bearer <token>" \
  -F "file=@recording.webm" \
  -F "language=auto"

# Text-to-speech (Kokoro, AWS Polly, or Piper — returns audio/mpeg)
curl -X POST http://localhost:8000/api/v1/chat/speak \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"text": "Hello, I am Bob!", "voice": "af_heart"}' \
  --output speech.mp3
```

### Email (Gmail)

```bash
# Check connected email accounts
curl http://localhost:8000/api/v1/email/connections \
  -H "Authorization: Bearer <token>"

# Connect Gmail (returns Google OAuth URL)
curl http://localhost:8000/api/v1/email/connect/gmail \
  -H "Authorization: Bearer <token>"

# Sync emails (fetch latest 20 inbox + 20 sent, triage with LLM)
curl -X POST http://localhost:8000/api/v1/email/sync \
  -H "Authorization: Bearer <token>"

# Get email inbox (supports ?status=pending|sent|skipped)
curl http://localhost:8000/api/v1/email/inbox \
  -H "Authorization: Bearer <token>"

# Get email stats (pending count, high urgency count)
curl http://localhost:8000/api/v1/email/stats \
  -H "Authorization: Bearer <token>"

# Get daily email summary
curl http://localhost:8000/api/v1/email/summary \
  -H "Authorization: Bearer <token>"

# Connect an IMAP/SMTP account (WorkMail, Outlook, etc.)
curl -X POST http://localhost:8000/api/v1/email/connect/imap \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"email": "user@company.com", "password": "...", "imap_host": "imap.mail.us-east-1.awsapps.com", "smtp_host": "smtp.mail.us-east-1.awsapps.com"}'

# List contacts (auto-extracted from synced emails)
curl http://localhost:8000/api/v1/email/contacts \
  -H "Authorization: Bearer <token>"

# Disconnect Gmail
curl -X POST http://localhost:8000/api/v1/email/disconnect/gmail \
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
│       ├── email.py          # Gmail OAuth, sync, inbox, actions
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
│   │   ├── local.py          # OpenAI-compatible provider
│   │   └── usage.py          # LLM usage tracking & spending limits
│   ├── chat/
│   │   ├── web_tools.py      # Web search, product search, URL fetch tools
│   │   └── email_tools.py    # Email tools for chat (send, search, summary)
│   ├── email/
│   │   ├── gmail.py           # Gmail OAuth2 client + API (fetch, send)
│   │   ├── imap_client.py     # Generic IMAP/SMTP client (WorkMail, Outlook, etc.)
│   │   └── sync_task.py       # Per-user email sync (on login + every 5 min)
│   ├── memory/
│   │   └── conversation.py   # DB-backed session store
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
| **Serper.dev** | Google Search API for web and product search |
| **Whisper** | Speech-to-text with auto language detection |
| **AWS Transcribe** | Cloud-based speech-to-text (alternative STT provider) |
| **Kokoro TTS** | GPU-accelerated text-to-speech (26 voices, chunked playback) |
| **AWS Polly** | Cloud-based TTS with generative voices |
| **Piper TTS** | Local TTS for natural-sounding Romanian voice |
| **Gmail API** | OAuth2 multi-tenant email integration (read, send, sync) |
| **BeautifulSoup** | Web page content extraction |
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
