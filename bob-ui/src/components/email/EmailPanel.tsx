import { useState, useEffect, useCallback } from 'react'
import {
  Mail, AlertCircle, Clock, Send, Edit3, X, Paperclip, RefreshCw,
  ChevronDown, ChevronUp, SkipForward, Shield, Zap, Inbox, LogOut, FileText,
} from 'lucide-react'
import { clsx } from 'clsx'
import { useSettings } from '../../store/settings'
import { useAuth } from '../../store/auth'
import {
  getEmailInbox,
  getEmailStats,
  getEmailConnections,
  getEmailSummary,
  connectGmail,
  disconnectGmail,
  syncEmails,
  emailAction,
  type EmailDigestItem,
  type EmailStats,
  type EmailConnections,
  type EmailSummary,
} from '../../api/client'

const URGENCY_CONFIG = {
  high: { color: 'text-red-400', bg: 'bg-red-500/20', border: 'border-red-500/30', label: 'Urgent' },
  medium: { color: 'text-amber-400', bg: 'bg-amber-500/20', border: 'border-amber-500/30', label: 'Medium' },
  low: { color: 'text-emerald-400', bg: 'bg-emerald-500/20', border: 'border-emerald-500/30', label: 'Low' },
}

const STATUS_FILTERS = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'sent', label: 'Sent' },
  { value: 'skipped', label: 'Skipped' },
]

// ---------------------------------------------------------------------------
// Gmail Connect Screen
// ---------------------------------------------------------------------------

function GmailConnectScreen({
  canConnect,
  onConnect,
  connecting,
}: {
  canConnect: boolean
  onConnect: () => void
  connecting: boolean
}) {
  return (
    <div className="h-full flex items-center justify-center bg-surface-800 px-4">
      <div className="max-w-md w-full text-center space-y-6">
        {/* Gmail icon */}
        <div className="mx-auto w-20 h-20 rounded-2xl bg-gradient-to-br from-red-500/20 to-amber-500/20 border border-red-500/20 flex items-center justify-center">
          <svg viewBox="0 0 24 24" className="w-10 h-10" fill="none">
            <path d="M2 6L12 13L22 6" stroke="#EA4335" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            <rect x="2" y="4" width="20" height="16" rx="2" stroke="#4285F4" strokeWidth="1.5" fill="none"/>
            <path d="M2 6L12 13" stroke="#FBBC05" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M22 6L12 13" stroke="#34A853" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-gray-100 mb-2">Connect your Gmail</h2>
          <p className="text-sm text-gray-400 leading-relaxed">
            Bob will read your emails, summarize them, and suggest quick replies.
            You stay in control — nothing is sent without your approval.
          </p>
        </div>

        {/* Features */}
        <div className="space-y-3 text-left">
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-surface-700/50">
            <Zap size={16} className="text-amber-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm text-gray-200 font-medium">Smart triage</p>
              <p className="text-xs text-gray-400">Each email gets urgency, category, and a one-line action</p>
            </div>
          </div>
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-surface-700/50">
            <Mail size={16} className="text-indigo-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm text-gray-200 font-medium">Draft replies</p>
              <p className="text-xs text-gray-400">Short reply suggestions you can send, edit, or skip in one click</p>
            </div>
          </div>
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-surface-700/50">
            <Shield size={16} className="text-emerald-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm text-gray-200 font-medium">Secure & private</p>
              <p className="text-xs text-gray-400">Google OAuth — Bob never sees your password. Disconnect anytime.</p>
            </div>
          </div>
        </div>

        {/* Connect button */}
        <div className="space-y-3 pt-2">
          {canConnect ? (
            <button
              onClick={onConnect}
              disabled={connecting}
              className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-medium text-sm transition-all bg-white text-gray-800 hover:bg-gray-100 shadow-lg shadow-white/10 disabled:opacity-50"
            >
              {connecting ? (
                <RefreshCw size={16} className="animate-spin" />
              ) : (
                <svg viewBox="0 0 24 24" className="w-5 h-5">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
                  <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                  <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                  <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                </svg>
              )}
              {connecting ? 'Connecting...' : 'Connect with Google'}
            </button>
          ) : (
            <div className="px-4 py-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm">
              Google OAuth not configured yet. Contact your admin.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main EmailPanel
// ---------------------------------------------------------------------------

export default function EmailPanel() {
  const { settings } = useSettings()
  const { auth } = useAuth()
  const authHeaders = { token: auth.token!, tenantSlug: auth.tenantSlug! }

  const [emails, setEmails] = useState<EmailDigestItem[]>([])
  const [stats, setStats] = useState<EmailStats | null>(null)
  const [connections, setConnections] = useState<EmailConnections | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [summary, setSummary] = useState<EmailSummary | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [showSummary, setShowSummary] = useState(false)

  const loadConnections = useCallback(async () => {
    try {
      const conns = await getEmailConnections(settings, authHeaders)
      setConnections(conns)
      return conns
    } catch {
      setConnections({ gmail: { connected: false, email: null, can_connect: false } })
      return null
    }
  }, [settings, auth.token, auth.tenantSlug])

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const [inbox, st] = await Promise.all([
        getEmailInbox(settings, authHeaders, filter || undefined),
        getEmailStats(settings, authHeaders),
      ])
      setEmails(inbox)
      setStats(st)
    } catch (e: any) {
      setError(e.message || 'Failed to load emails')
    } finally {
      setLoading(false)
    }
  }, [settings, auth.token, auth.tenantSlug, filter])

  useEffect(() => {
    loadConnections().then(() => load())
  }, [])

  useEffect(() => { load() }, [filter])

  // Auto-refresh every 2 minutes
  useEffect(() => {
    const id = setInterval(load, 120_000)
    return () => clearInterval(id)
  }, [load])

  // Check URL params for gmail_connected redirect
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('gmail_connected') === '1') {
      loadConnections().then(() => load())
      window.history.replaceState({}, '', window.location.pathname)
    }
    const emailError = params.get('email_error')
    if (emailError) {
      setError(`Gmail connection failed: ${emailError}`)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  const handleConnect = async () => {
    try {
      setConnecting(true)
      const { auth_url } = await connectGmail(settings, authHeaders)
      window.location.href = auth_url
    } catch (e: any) {
      setError(e.message)
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    if (!confirm('Disconnect Gmail? Bob will stop reading your emails.')) return
    try {
      await disconnectGmail(settings, authHeaders)
      await loadConnections()
      setEmails([])
      setStats(null)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleSync = async () => {
    try {
      setSyncing(true)
      setError(null)
      const result = await syncEmails(settings, authHeaders)
      if (result.errors?.length) {
        setError(result.errors.join(', '))
      }
      await load()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSyncing(false)
    }
  }

  const handleSummary = async () => {
    try {
      setSummaryLoading(true)
      setShowSummary(true)
      const s = await getEmailSummary(settings, authHeaders)
      setSummary(s)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSummaryLoading(false)
    }
  }

  const handleAction = async (id: string, action: 'send' | 'skip' | 'edit', reply?: string) => {
    try {
      setActionLoading(id)
      const updated = await emailAction(id, action, settings, authHeaders, reply)
      setEmails(prev => prev.map(e => e.id === id ? updated : e))
      setEditingId(null)
      const st = await getEmailStats(settings, authHeaders)
      setStats(st)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActionLoading(null)
    }
  }

  const formatTime = (iso: string | null) => {
    if (!iso) return ''
    const d = new Date(iso)
    const now = new Date()
    const diffH = (now.getTime() - d.getTime()) / 3600000
    if (diffH < 1) return `${Math.round(diffH * 60)}m ago`
    if (diffH < 24) return `${Math.round(diffH)}h ago`
    return d.toLocaleDateString('ro-RO', { day: 'numeric', month: 'short' })
  }

  // Show connect screen if Gmail not connected
  if (connections && !connections.gmail.connected && emails.length === 0 && !loading) {
    return (
      <GmailConnectScreen
        canConnect={connections.gmail.can_connect}
        onConnect={handleConnect}
        connecting={connecting}
      />
    )
  }

  return (
    <div className="h-full flex flex-col bg-surface-800">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-4 border-b border-surface-700">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Mail size={20} className="text-indigo-400" />
            <h2 className="text-lg font-semibold text-gray-100">Email Inbox</h2>
            {connections?.gmail?.connected && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/20">
                {connections.gmail.email || 'Gmail'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {connections?.gmail?.connected && (
              <button
                onClick={handleSummary}
                disabled={summaryLoading}
                title="Daily summary"
                className="p-2 rounded-lg text-gray-400 hover:text-indigo-400 hover:bg-indigo-900/20 transition-colors"
              >
                <FileText size={16} className={summaryLoading ? 'animate-pulse' : ''} />
              </button>
            )}
            {connections?.gmail?.connected && (
              <button
                onClick={handleSync}
                disabled={syncing}
                title="Sync new emails"
                className="p-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-surface-700 transition-colors"
              >
                <RefreshCw size={16} className={syncing ? 'animate-spin' : ''} />
              </button>
            )}
            {connections?.gmail?.connected && (
              <button
                onClick={handleDisconnect}
                title="Disconnect Gmail"
                className="p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-red-900/20 transition-colors"
              >
                <LogOut size={14} />
              </button>
            )}
          </div>
        </div>

        {/* Stats bar */}
        {stats && (stats.pending > 0 || stats.high_urgency > 0) && (
          <div className="flex gap-3 mb-3">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-700 text-xs">
              <Clock size={12} className="text-amber-400" />
              <span className="text-gray-300">{stats.pending} pending</span>
            </div>
            {stats.high_urgency > 0 && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-red-500/10 border border-red-500/20 text-xs">
                <AlertCircle size={12} className="text-red-400" />
                <span className="text-red-300">{stats.high_urgency} urgent</span>
              </div>
            )}
          </div>
        )}

        {/* Filter */}
        <div className="flex gap-1.5">
          {STATUS_FILTERS.map(f => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={clsx(
                'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                filter === f.value
                  ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-surface-700',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Email list */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="mx-4 mt-4 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300"><X size={14} /></button>
          </div>
        )}

        {/* Daily summary panel */}
        {showSummary && (
          <div className="mx-4 mt-4 p-4 rounded-xl bg-indigo-500/10 border border-indigo-500/20">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <FileText size={14} className="text-indigo-400" />
                <span className="text-sm font-medium text-indigo-300">Rezumat zilnic</span>
                {summary && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400">
                    {summary.email_count} emailuri
                  </span>
                )}
              </div>
              <button onClick={() => setShowSummary(false)} className="text-gray-400 hover:text-gray-300">
                <X size={14} />
              </button>
            </div>
            {summaryLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <RefreshCw size={14} className="animate-spin" />
                Generez rezumatul...
              </div>
            ) : summary ? (
              <div className="space-y-2">
                <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">{summary.summary}</p>
                {Object.keys(summary.categories).length > 0 && (
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {Object.entries(summary.categories).map(([cat, count]) => (
                      <span key={cat} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-600 text-gray-400">
                        {cat} ({count})
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}

        {loading && emails.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-gray-500 text-sm">
            <RefreshCw size={16} className="animate-spin mr-2" />
            Loading emails...
          </div>
        ) : emails.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-500">
            <Inbox size={32} className="mb-3 opacity-40" />
            <p className="text-sm">No emails yet</p>
            <p className="text-xs mt-1 text-gray-600">Click the sync button to fetch your latest emails</p>
          </div>
        ) : (
          <div className="divide-y divide-surface-700">
            {emails.map(email => {
              const urgency = URGENCY_CONFIG[email.urgency] || URGENCY_CONFIG.low
              const isExpanded = expandedId === email.id
              const isEditing = editingId === email.id
              const isLoading = actionLoading === email.id

              return (
                <div
                  key={email.id}
                  className={clsx(
                    'px-4 py-3 transition-colors',
                    email.status === 'pending' ? 'hover:bg-surface-700/50' : 'opacity-60',
                  )}
                >
                  {/* Row header */}
                  <div
                    className="flex items-start gap-2 cursor-pointer"
                    onClick={() => setExpandedId(isExpanded ? null : email.id)}
                  >
                    <div className={clsx('mt-1 w-2 h-2 rounded-full flex-shrink-0', urgency.bg, urgency.border, 'border')} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-200 truncate">{email.sender}</span>
                        {email.attachments.length > 0 && <Paperclip size={12} className="text-gray-500 flex-shrink-0" />}
                        {email.status !== 'pending' && (
                          <span className={clsx(
                            'text-[10px] px-1.5 py-0.5 rounded font-medium',
                            email.status === 'sent' ? 'bg-emerald-500/20 text-emerald-400' :
                            email.status === 'skipped' ? 'bg-gray-500/20 text-gray-400' :
                            'bg-blue-500/20 text-blue-400'
                          )}>{email.status}</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 truncate mt-0.5">{email.subject}</p>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <span className="text-[10px] text-gray-500">{formatTime(email.received_at)}</span>
                      {isExpanded ? <ChevronUp size={14} className="text-gray-500" /> : <ChevronDown size={14} className="text-gray-500" />}
                    </div>
                  </div>

                  {/* Action summary (always visible) */}
                  {email.action && (
                    <div className="mt-1.5 ml-4">
                      <span className="text-xs text-gray-300 leading-relaxed">{email.action}</span>
                    </div>
                  )}

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="mt-3 ml-4 space-y-2">
                      {/* Urgency + Category badges */}
                      <div className="flex items-center gap-2">
                        <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-medium', urgency.bg, urgency.color)}>{urgency.label}</span>
                        {email.category && <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-600 text-gray-300">{email.category}</span>}
                      </div>

                      {/* Attachments */}
                      {email.attachments.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {email.attachments.map((a, i) => (
                            <span key={i} className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-surface-600 text-gray-400">
                              <Paperclip size={10} />{a.name}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Reply draft */}
                      {email.reply_draft && !isEditing && (
                        <div className="p-2.5 rounded-lg bg-surface-700 border border-surface-600">
                          <p className="text-[10px] text-gray-500 mb-1 font-medium uppercase tracking-wide">Suggested reply</p>
                          <p className="text-xs text-gray-300 leading-relaxed">{email.reply_draft}</p>
                        </div>
                      )}

                      {/* Edit mode */}
                      {isEditing && (
                        <div className="space-y-2">
                          <textarea
                            value={editText}
                            onChange={e => setEditText(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg bg-surface-700 border border-surface-600 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none resize-none"
                            rows={3}
                            autoFocus
                          />
                          <div className="flex gap-2">
                            <button onClick={() => handleAction(email.id, 'edit', editText)} disabled={isLoading} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50">
                              <Send size={12} /> Save
                            </button>
                            <button onClick={() => setEditingId(null)} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-600 hover:bg-surface-500 text-gray-300 text-xs transition-colors">
                              <X size={12} /> Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Action buttons */}
                      {email.status === 'pending' && !isEditing && (
                        <div className="flex gap-2 pt-1">
                          {email.reply_draft && (
                            <>
                              <button onClick={() => handleAction(email.id, 'send')} disabled={isLoading} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-400 text-xs font-medium transition-colors disabled:opacity-50">
                                <Send size={12} /> Send Reply
                              </button>
                              <button onClick={() => { setEditingId(email.id); setEditText(email.reply_draft || '') }} disabled={isLoading} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-600 hover:bg-surface-500 text-gray-300 text-xs transition-colors disabled:opacity-50">
                                <Edit3 size={12} /> Edit
                              </button>
                            </>
                          )}
                          <button onClick={() => handleAction(email.id, 'skip')} disabled={isLoading} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-600 hover:bg-surface-500 text-gray-400 text-xs transition-colors disabled:opacity-50">
                            <SkipForward size={12} /> Skip
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
