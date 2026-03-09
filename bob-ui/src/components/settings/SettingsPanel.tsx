import { useState, useEffect } from 'react'
import { Settings, RotateCcw, CheckCircle2, XCircle, Loader2, Key, Plus, Copy, Trash2, ExternalLink, LogOut } from 'lucide-react'
import { useSettings } from '../../store/settings'
import { useAuth } from '../../store/auth'
import { healthCheck, createApiToken, listApiTokens, revokeApiToken, ApiTokenInfo } from '../../api/client'

export default function SettingsPanel() {
  const { settings, update, reset } = useSettings()
  const { auth, logout } = useAuth()
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<boolean | null>(null)
  const [saved, setSaved] = useState(false)

  // API Tokens state
  const [tokens, setTokens] = useState<ApiTokenInfo[]>([])
  const [tokensLoading, setTokensLoading] = useState(true)
  const [newTokenName, setNewTokenName] = useState('')
  const [creating, setCreating] = useState(false)
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [tokenError, setTokenError] = useState<string | null>(null)

  const test = async () => {
    setTesting(true)
    setTestResult(null)
    const ok = await healthCheck(settings.baseUrl || '')
    setTestResult(ok)
    setTesting(false)
  }

  const save = () => {
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  // Fetch tokens on mount
  useEffect(() => {
    if (auth.token && auth.tenantSlug) {
      loadTokens()
    }
  }, [])

  const loadTokens = async () => {
    setTokensLoading(true)
    try {
      const authH = { token: auth.token!, tenantSlug: auth.tenantSlug! }
      const list = await listApiTokens(settings, authH)
      setTokens(list)
    } catch (e) {
      setTokenError(e instanceof Error ? e.message : 'Failed to load tokens')
    } finally {
      setTokensLoading(false)
    }
  }

  const handleCreateToken = async () => {
    if (!newTokenName.trim()) return
    setCreating(true)
    setTokenError(null)
    setNewlyCreatedToken(null)
    try {
      const authH = { token: auth.token!, tenantSlug: auth.tenantSlug! }
      const result = await createApiToken(newTokenName.trim(), settings, authH)
      setNewlyCreatedToken(result.token)
      setNewTokenName('')
      await loadTokens()
    } catch (e) {
      setTokenError(e instanceof Error ? e.message : 'Failed to create token')
    } finally {
      setCreating(false)
    }
  }

  const handleRevokeToken = async (tokenId: string) => {
    if (!confirm('Revoke this token? It will immediately stop working.')) return
    try {
      const authH = { token: auth.token!, tenantSlug: auth.tenantSlug! }
      await revokeApiToken(tokenId, settings, authH)
      await loadTokens()
    } catch (e) {
      setTokenError(e instanceof Error ? e.message : 'Failed to revoke token')
    }
  }

  const copyToken = async () => {
    if (!newlyCreatedToken) return
    try {
      // Try modern Clipboard API first
      await navigator.clipboard.writeText(newlyCreatedToken)
    } catch {
      // Fallback: create a temporary textarea and use execCommand
      const textarea = document.createElement('textarea')
      textarea.value = newlyCreatedToken
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 max-w-2xl mx-auto space-y-4 md:space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-gray-600/20 border border-gray-500/30 flex items-center justify-center">
          <Settings size={18} className="text-gray-400" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-gray-100">Settings</h1>
          <p className="text-xs text-gray-500">Stored in your browser's localStorage</p>
        </div>
      </div>

      {/* Account info */}
      <section className="card space-y-3">
        <h2 className="text-sm font-semibold text-gray-200">Account</h2>
        <div className="space-y-1 text-sm">
          <p className="text-gray-400">
            <span className="text-gray-500">Name:</span>{' '}
            <span className="text-gray-200">{auth.user?.name}</span>
          </p>
          <p className="text-gray-400">
            <span className="text-gray-500">Email:</span>{' '}
            <span className="text-gray-200">{auth.user?.email}</span>
          </p>
          <p className="text-gray-400">
            <span className="text-gray-500">Tenant:</span>{' '}
            <span className="font-mono text-indigo-400">{auth.tenantSlug}</span>
          </p>
        </div>
        <button
          onClick={logout}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-red-400 hover:bg-red-900/20 transition-colors border border-red-800/30"
        >
          <LogOut size={14} />
          Sign out
        </button>
      </section>

      {/* API Tokens */}
      <section className="card space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
            <Key size={14} /> API Tokens
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Generate tokens for external integrations (n8n, curl, etc.).
            Tokens include your tenant context — no extra headers needed.
          </p>
        </div>

        {/* Newly created token banner */}
        {newlyCreatedToken && (
          <div className="bg-emerald-950/40 border border-emerald-800/50 rounded-lg p-3 space-y-2">
            <p className="text-xs text-emerald-400 font-medium">
              Token created! Copy it now — it won't be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-surface-900 rounded px-3 py-2 text-xs font-mono text-gray-200 break-all select-all">
                {newlyCreatedToken}
              </code>
              <button onClick={copyToken} className="btn-ghost border border-surface-600 text-sm flex-shrink-0">
                {copied ? <CheckCircle2 size={14} className="text-emerald-400" /> : <Copy size={14} />}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>
        )}

        {/* Create new token */}
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <label className="text-xs text-gray-400 mb-1.5 block">Token name</label>
            <input
              value={newTokenName}
              onChange={e => setNewTokenName(e.target.value)}
              placeholder='e.g. "n8n automation"'
              className="input"
              onKeyDown={e => e.key === 'Enter' && handleCreateToken()}
            />
          </div>
          <button
            onClick={handleCreateToken}
            disabled={creating || !newTokenName.trim()}
            className="btn-primary"
          >
            {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            Generate
          </button>
        </div>

        {/* Error */}
        {tokenError && (
          <div className="bg-red-950/40 border border-red-800/50 text-red-400 text-xs px-3 py-2 rounded-lg">
            {tokenError}
          </div>
        )}

        {/* Token list */}
        {tokensLoading ? (
          <div className="text-xs text-gray-500 flex items-center gap-2">
            <Loader2 size={12} className="animate-spin" /> Loading tokens...
          </div>
        ) : tokens.length === 0 ? (
          <p className="text-xs text-gray-500">No API tokens yet.</p>
        ) : (
          <div className="space-y-2">
            {tokens.map(t => (
              <div key={t.id} className="flex items-center justify-between bg-surface-900 rounded-lg px-3 py-2.5 border border-surface-700">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-200 font-medium truncate">{t.name}</span>
                    {t.is_revoked && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/30 text-red-400 border border-red-800/30">Revoked</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                    <span className="font-mono">bob_...{t.token_prefix}</span>
                    <span>Created {new Date(t.created_at).toLocaleDateString()}</span>
                    {t.last_used_at && <span>Last used {new Date(t.last_used_at).toLocaleDateString()}</span>}
                  </div>
                </div>
                {!t.is_revoked && (
                  <button
                    onClick={() => handleRevokeToken(t.id)}
                    className="btn-ghost border border-red-800/30 text-red-400 hover:bg-red-900/20 text-xs flex-shrink-0 ml-2"
                  >
                    <Trash2 size={13} /> Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* API docs link + usage example */}
        {tokens.some(t => !t.is_revoked) && (
          <div className="space-y-2">
            <a
              href={`${settings.baseUrl || ''}/docs`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              <ExternalLink size={13} />
              View API Documentation (Swagger UI)
            </a>
            <div className="bg-surface-900 rounded-lg p-3 border border-surface-700">
              <p className="text-xs text-gray-400 mb-1.5">Usage example:</p>
              <code className="text-xs font-mono text-gray-400 block whitespace-pre overflow-x-auto">{`curl ${window.location.origin}/api/v1/chat/ \\
  -H "Authorization: Bearer bob_YOUR_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Hello Bob"}'`}</code>
            </div>
          </div>
        )}
      </section>

      {/* Connection */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold text-gray-200">API Connection</h2>

        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">Base URL</label>
          <input
            value={settings.baseUrl}
            onChange={e => update({ baseUrl: e.target.value })}
            placeholder="Leave empty to use Vite proxy (http://localhost:8000)"
            className="input"
          />
          <p className="text-xs text-gray-600 mt-1">
            Leave empty when running the UI dev server — requests are proxied to <code className="text-gray-500">localhost:8000</code> automatically.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button onClick={test} disabled={testing} className="btn-ghost border border-surface-600 text-sm">
            {testing ? <Loader2 size={14} className="animate-spin" /> : null}
            {testing ? 'Testing...' : 'Test connection'}
          </button>
          {testResult === true && (
            <span className="flex items-center gap-1.5 text-emerald-400 text-sm">
              <CheckCircle2 size={14} /> Connected
            </span>
          )}
          {testResult === false && (
            <span className="flex items-center gap-1.5 text-red-400 text-sm">
              <XCircle size={14} /> Failed — check URL
            </span>
          )}
        </div>
      </section>

      {/* Model */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold text-gray-200">Model</h2>
        <div className="space-y-1 text-xs text-gray-400">
          <p>The active model is configured in the backend <code className="text-gray-300">.env</code> file.</p>
          <div className="bg-surface-900 rounded-lg p-3 space-y-1 font-mono text-gray-400 border border-surface-700">
            <p><span className="text-gray-600">LLM_PROVIDER=</span><span className="text-indigo-400">local</span></p>
            <p><span className="text-gray-600">LOCAL_MODEL_NAME=</span><span className="text-emerald-400">your-model-name</span></p>
            <p><span className="text-gray-600">LOCAL_MODEL_EMBED_NAME=</span><span className="text-emerald-400">text-embedding-nomic-embed-text-v1.5</span></p>
            <p><span className="text-gray-600">LOCAL_MODEL_BASE_URL=</span><span className="text-amber-400">http://localhost:1234/v1</span></p>
          </div>
          <p className="mt-2">To switch to Bedrock, set <code className="text-gray-300">LLM_PROVIDER=bedrock</code> and add AWS credentials in the .env file, then restart the API server.</p>
        </div>
      </section>

      {/* Behaviour */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold text-gray-200">Behaviour</h2>

        <div>
          <label className="text-xs text-gray-400 mb-1.5 block">System prompt</label>
          <textarea
            value={settings.systemPrompt}
            onChange={e => update({ systemPrompt: e.target.value })}
            rows={4}
            className="input resize-none"
            placeholder="You are Bob, a helpful AI assistant."
          />
          <p className="text-xs text-gray-600 mt-1">
            Sent as the system message on every chat request. Leave empty to use the server default.
          </p>
        </div>
      </section>

      {/* Actions */}
      <div className="flex items-center gap-3 pb-6">
        <button onClick={save} className="btn-primary">
          {saved ? <CheckCircle2 size={14} /> : null}
          {saved ? 'Saved!' : 'Save settings'}
        </button>
        <button
          onClick={() => { if (confirm('Reset all settings to defaults?')) reset() }}
          className="btn-ghost border border-surface-600 text-sm text-gray-400"
        >
          <RotateCcw size={13} /> Reset to defaults
        </button>
      </div>
    </div>
  )
}
