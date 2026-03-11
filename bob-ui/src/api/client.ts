// Typed API client for the Bob backend

// Global auth-error handler — set by AuthProvider to trigger auto-logout on 401
let _onAuthError: (() => void) | null = null
export function setOnAuthError(fn: (() => void) | null) { _onAuthError = fn }

// Global token-refresh handler — set by AuthProvider to silently update the stored JWT
let _onTokenRefresh: ((newToken: string) => void) | null = null
export function setOnTokenRefresh(fn: ((newToken: string) => void) | null) { _onTokenRefresh = fn }

// ---------------------------------------------------------------------------
// Request timeout helper
// ---------------------------------------------------------------------------

const DEFAULT_TIMEOUT_MS = 30_000  // 30 seconds
const AGENT_TIMEOUT_MS = 180_000   // 3 minutes for agent tasks

function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit & { timeoutMs?: number },
): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchInit } = init ?? {}
  const controller = new AbortController()
  const id = setTimeout(() => controller.abort(), timeoutMs)

  return fetch(input, { ...fetchInit, signal: controller.signal })
    .then(res => { clearTimeout(id); return res })
    .catch(err => {
      clearTimeout(id)
      if (err.name === 'AbortError') throw new Error(`Request timed out after ${timeoutMs / 1000}s`)
      throw err
    })
}

export interface Settings {
  apiKey: string
  baseUrl: string
  systemPrompt: string
}

export interface AuthHeaders {
  token: string
  tenantSlug: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  messageId?: string
  inputTokens?: number
  outputTokens?: number
}

export interface ChatResponse {
  session_id: string
  message_id: string
  content: string
  model?: string
  input_tokens?: number
  output_tokens?: number
  knowledge_used?: boolean
  knowledge_sources?: string[]
}

export interface SessionSummary {
  session_id: string
  title: string | null
  created_at: string
  updated_at: string
}

export interface ArchiveResponse {
  session_id: string
  document_id: string
  chunks: number
  message: string
}

export interface SessionTurn {
  turn_id: string
  user: string
  assistant: string
  created_at: string
}

export interface SessionHistory {
  session_id: string
  turns: SessionTurn[]
  total_turns: number
}

export interface SourceDocument {
  document_id: string
  source: string
  format: string
  excerpt: string
}

export interface RAGQueryResponse {
  answer: string
  query: string
  sources: SourceDocument[]
  chunks_retrieved: number
}

export interface IngestResponse {
  document_id: string
  filename: string
  chunks: number
  format: string
  message: string
}

export interface DocumentInfo {
  document_id: string
  source: string
  format: string
  chunk_count: number
}

export interface ToolCall {
  tool_name: string
  input: Record<string, unknown>
  output: string
  duration_ms: number
}

export interface AgentRunResponse {
  run_id: string
  task: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  output?: string
  steps: string[]
  tool_calls: ToolCall[]
  error?: string
  started_at?: string
  completed_at?: string
  duration_seconds?: number
}

// ---------------------------------------------------------------------------

function authHeaders(auth: AuthHeaders): HeadersInit {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${auth.token}`,
    'X-Tenant-ID': auth.tenantSlug,
  }
}

function authHeadersNoBody(auth: AuthHeaders): HeadersInit {
  return {
    Authorization: `Bearer ${auth.token}`,
    'X-Tenant-ID': auth.tenantSlug,
  }
}

/** Extract X-New-Token from response and silently update stored JWT */
function _maybeRefreshToken(res: Response): void {
  const newToken = res.headers.get('X-New-Token')
  if (newToken && _onTokenRefresh) {
    _onTokenRefresh(newToken)
  }
}

/** Check response for 401 and trigger auto-logout, also handle token refresh */
function check401(res: Response): Response {
  if (res.status === 401 && _onAuthError) {
    _onAuthError()
    throw new Error('Session expired — please sign in again')
  }
  _maybeRefreshToken(res)
  return res
}

// ── Auth endpoints (no token needed) ──────────────────────────────────────

export async function apiLogin(
  baseUrl: string,
  email: string,
  password: string,
): Promise<{ access_token: string; token_type: string; tenant_slug: string }> {
  const res = await fetchWithTimeout(`${baseUrl}/api/v1/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail ?? res.statusText)
  }
  return res.json()
}

export async function apiRegister(
  baseUrl: string,
  email: string,
  password: string,
  name: string,
): Promise<{ user_id: string; email: string; name: string; message: string }> {
  const res = await fetchWithTimeout(`${baseUrl}/api/v1/auth/register`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password, name }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail ?? res.statusText)
  }
  return res.json()
}

// ── Chat ──────────────────────────────────────────────────────────────────

export async function sendChat(
  message: string,
  sessionId: string | undefined,
  settings: Settings,
  auth: AuthHeaders,
  useKnowledge: boolean = false,
): Promise<ChatResponse> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/chat/`, {
    method: 'POST',
    headers: authHeaders(auth),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      system_prompt: settings.systemPrompt || undefined,
      use_knowledge: useKnowledge,
    }),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

export async function* streamChat(
  message: string,
  sessionId: string | undefined,
  settings: Settings,
  auth: AuthHeaders,
  useKnowledge: boolean = false,
): AsyncGenerator<{ chunk?: string; done?: boolean; session_id?: string; error?: string; knowledge_used?: boolean; knowledge_sources?: string[] }> {
  const res = check401(await fetch(`${settings.baseUrl}/api/v1/chat/`, {
    method: 'POST',
    headers: authHeaders(auth),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      stream: true,
      system_prompt: settings.systemPrompt || undefined,
      use_knowledge: useKnowledge,
    }),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          yield JSON.parse(line.slice(6))
        } catch { /* ignore malformed */ }
      }
    }
  }
}

export async function listSessions(settings: Settings, auth: AuthHeaders): Promise<SessionSummary[]> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/chat/sessions`, {
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  const data = await res.json()
  return data.sessions
}

export async function getHistory(sessionId: string, settings: Settings, auth: AuthHeaders): Promise<SessionHistory> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/chat/${sessionId}/history`, {
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

export async function deleteSession(sessionId: string, settings: Settings, auth: AuthHeaders): Promise<void> {
  check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/chat/${sessionId}`, {
    method: 'DELETE',
    headers: authHeadersNoBody(auth),
  }))
}

export async function archiveSession(sessionId: string, settings: Settings, auth: AuthHeaders): Promise<ArchiveResponse> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/chat/${sessionId}/archive`, {
    method: 'POST',
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

export interface ChatUploadResponse {
  session_id: string
  message_id: string
  content: string
  document_id: string
  filename: string
  chunks: number
}

export async function uploadChatFile(
  file: File,
  sessionId: string | undefined,
  message: string,
  settings: Settings,
  auth: AuthHeaders,
): Promise<ChatUploadResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('message', message || '')
  if (sessionId) form.append('session_id', sessionId)
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/chat/upload`, {
    method: 'POST',
    headers: authHeadersNoBody(auth),
    body: form,
    timeoutMs: 120_000,
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

// ── RAG ───────────────────────────────────────────────────────────────────

export async function ragQuery(query: string, k: number, settings: Settings, auth: AuthHeaders): Promise<RAGQueryResponse> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/rag/query`, {
    method: 'POST',
    headers: authHeaders(auth),
    body: JSON.stringify({ query, k }),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

export async function ingestFile(file: File, settings: Settings, auth: AuthHeaders): Promise<IngestResponse> {
  const form = new FormData()
  form.append('file', file)
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/rag/ingest`, {
    method: 'POST',
    headers: authHeadersNoBody(auth),
    body: form,
    timeoutMs: 120_000,  // file uploads may take longer
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

export async function listDocuments(settings: Settings, auth: AuthHeaders): Promise<DocumentInfo[]> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/rag/documents`, {
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  const data = await res.json()
  return data.documents
}

export async function deleteDocument(documentId: string, settings: Settings, auth: AuthHeaders): Promise<void> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/rag/documents/${documentId}`, {
    method: 'DELETE',
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
}

// ── Agent ─────────────────────────────────────────────────────────────────

export async function runAgent(task: string, settings: Settings, auth: AuthHeaders): Promise<AgentRunResponse> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/agent/run`, {
    method: 'POST',
    headers: authHeaders(auth),
    body: JSON.stringify({ task }),
    timeoutMs: AGENT_TIMEOUT_MS,
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

// ── API Tokens ────────────────────────────────────────────────────────────

export interface ApiTokenInfo {
  id: string
  name: string
  token_prefix: string
  is_revoked: boolean
  last_used_at: string | null
  created_at: string
}

export interface CreateTokenResponse {
  id: string
  name: string
  token: string // Raw token, shown once
  token_prefix: string
  created_at: string
}

export async function createApiToken(
  name: string,
  settings: Settings,
  auth: AuthHeaders,
): Promise<CreateTokenResponse> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/tokens/`, {
    method: 'POST',
    headers: authHeaders(auth),
    body: JSON.stringify({ name }),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  return res.json()
}

export async function listApiTokens(
  settings: Settings,
  auth: AuthHeaders,
): Promise<ApiTokenInfo[]> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/tokens/`, {
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
  const data = await res.json()
  return data.tokens
}

export async function revokeApiToken(
  tokenId: string,
  settings: Settings,
  auth: AuthHeaders,
): Promise<void> {
  const res = check401(await fetchWithTimeout(`${settings.baseUrl}/api/v1/tokens/${tokenId}`, {
    method: 'DELETE',
    headers: authHeadersNoBody(auth),
  }))
  if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText)
}

// ── Health ─────────────────────────────────────────────────────────────────

export async function healthCheck(baseUrl: string): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl}/health`)
    return res.ok
  } catch {
    return false
  }
}
