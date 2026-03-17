import { useState, useRef, useCallback, useEffect } from 'react'
import { Upload, Search, FileText, File, Loader2, ChevronDown, ChevronUp, BookOpen, Trash2, Mail, ChevronLeft, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'
import ReactMarkdown from 'react-markdown'
import { useSettings } from '../../store/settings'
import { useAuth } from '../../store/auth'
import { ingestFile, ragQuery, listDocuments, deleteDocument } from '../../api/client'
import type { DocumentInfo, RAGQueryResponse, AuthHeaders } from '../../api/client'

const PAGE_SIZE = 10

export default function RAGPanel() {
  const { settings } = useSettings()
  const { auth } = useAuth()
  const authHeaders: AuthHeaders = { token: auth.token!, tenantSlug: auth.tenantSlug! }

  // Documents state
  const [docs, setDocs] = useState<DocumentInfo[]>([])
  const [loadingDocs, setLoadingDocs] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Emails state
  const [emails, setEmails] = useState<DocumentInfo[]>([])
  const [emailTotal, setEmailTotal] = useState(0)
  const [emailPage, setEmailPage] = useState(0)
  const [emailSearch, setEmailSearch] = useState('')
  const [emailSearchInput, setEmailSearchInput] = useState('')
  const [loadingEmails, setLoadingEmails] = useState(false)

  // Query state
  const [query, setQuery] = useState('')
  const [querying, setQuerying] = useState(false)
  const [result, setResult] = useState<RAGQueryResponse | null>(null)
  const [queryError, setQueryError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Fetch file documents (no source_type filter excludes emails — we filter client-side)
  const refreshDocs = useCallback(async () => {
    setLoadingDocs(true)
    try {
      const data = await listDocuments(settings, authHeaders, { limit: 200 })
      setDocs(data.documents.filter(d => d.source_type !== 'email'))
    } catch { /* ignore */ } finally {
      setLoadingDocs(false)
    }
  }, [settings, auth.token])

  // Fetch email documents
  const refreshEmails = useCallback(async () => {
    setLoadingEmails(true)
    try {
      const data = await listDocuments(settings, authHeaders, {
        sourceType: 'email',
        search: emailSearch || undefined,
        limit: PAGE_SIZE,
        offset: emailPage * PAGE_SIZE,
      })
      setEmails(data.documents)
      setEmailTotal(data.total)
    } catch { /* ignore */ } finally {
      setLoadingEmails(false)
    }
  }, [settings, auth.token, emailSearch, emailPage])

  useEffect(() => { refreshDocs() }, [refreshDocs])
  useEffect(() => { refreshEmails() }, [refreshEmails])

  const handleFiles = async (files: FileList | File[]) => {
    const arr = Array.from(files)
    if (!arr.length) return
    setUploading(true)
    setUploadMsg(null)
    let ok = 0, fail = 0
    for (const f of arr) {
      try {
        await ingestFile(f, settings, authHeaders)
        ok++
      } catch { fail++ }
    }
    setUploadMsg({
      type: fail === 0 ? 'ok' : 'err',
      text: fail === 0
        ? `${ok} file${ok > 1 ? 's' : ''} ingested successfully`
        : `${ok} ok, ${fail} failed`,
    })
    setUploading(false)
    refreshDocs()
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }

  const handleDelete = async (documentId: string) => {
    setDeletingId(documentId)
    try {
      await deleteDocument(documentId, settings, authHeaders)
      refreshDocs()
      refreshEmails()
    } catch { /* ignore */ } finally {
      setDeletingId(null)
    }
  }

  const search = async () => {
    if (!query.trim() || querying) return
    setQuerying(true)
    setQueryError(null)
    setResult(null)
    try {
      setResult(await ragQuery(query.trim(), 4, settings, authHeaders))
    } catch (e: unknown) {
      setQueryError(e instanceof Error ? e.message : 'Query failed')
    } finally {
      setQuerying(false)
    }
  }

  const handleEmailSearch = () => {
    setEmailPage(0)
    setEmailSearch(emailSearchInput.trim())
  }

  const totalPages = Math.max(1, Math.ceil(emailTotal / PAGE_SIZE))

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 space-y-4 md:space-y-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-violet-600/20 border border-violet-500/30 flex items-center justify-center">
          <BookOpen size={18} className="text-violet-400" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-gray-100">Knowledge Base</h1>
          <p className="text-xs text-gray-500">Documents, emails, and semantic search</p>
        </div>
      </div>

      {/* Upload zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        className={clsx(
          'border-2 border-dashed rounded-xl p-5 md:p-8 text-center cursor-pointer transition-all',
          dragOver
            ? 'border-violet-500 bg-violet-500/10'
            : 'border-surface-600 hover:border-surface-500 hover:bg-surface-800/50',
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".pdf,.txt,.md,.docx"
          multiple
          onChange={e => e.target.files && handleFiles(e.target.files)}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-2">
            <Loader2 size={24} className="text-violet-400 animate-spin" />
            <p className="text-sm text-gray-400">Ingesting…</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <Upload size={24} className="text-gray-500" />
            <p className="text-sm text-gray-300 font-medium">Drop files here or click to upload</p>
            <p className="text-xs text-gray-500">PDF · TXT · Markdown · DOCX — max 50 MB each</p>
          </div>
        )}
      </div>

      {uploadMsg && (
        <div className={clsx(
          'px-4 py-2.5 rounded-lg text-sm border animate-fade-in',
          uploadMsg.type === 'ok'
            ? 'bg-emerald-950/40 border-emerald-800/50 text-emerald-400'
            : 'bg-red-950/40 border-red-800/50 text-red-400',
        )}>
          {uploadMsg.text}
        </div>
      )}

      {/* Ingested documents */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium text-gray-300">
            Documents
            {docs.length > 0 && (
              <span className="ml-2 badge bg-surface-700 text-gray-400">{docs.length}</span>
            )}
          </h2>
          <button onClick={refreshDocs} className="btn-ghost text-xs py-1 px-2">
            {loadingDocs ? <Loader2 size={12} className="animate-spin" /> : 'Refresh'}
          </button>
        </div>

        {docs.length === 0 ? (
          <p className="text-xs text-gray-600 text-center py-6 card">No documents yet. Upload some files above.</p>
        ) : (
          <div className="space-y-2">
            {docs.map(doc => (
              <div key={doc.document_id} className="card flex items-center gap-3 py-3">
                <div className="w-8 h-8 rounded-lg bg-surface-700 flex items-center justify-center flex-shrink-0">
                  {doc.format === 'pdf' ? <File size={14} className="text-red-400" /> : <FileText size={14} className="text-blue-400" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-200 truncate font-medium">{doc.source}</p>
                  <p className="text-xs text-gray-500">{doc.chunk_count} chunks · {doc.format}</p>
                </div>
                <span className="badge bg-surface-700 text-gray-400 text-[10px]">{doc.format.toUpperCase()}</span>
                <button
                  onClick={() => handleDelete(doc.document_id)}
                  disabled={deletingId === doc.document_id}
                  className="p-1.5 rounded-lg text-gray-600 hover:text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-40"
                  title="Delete document"
                >
                  {deletingId === doc.document_id
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Trash2 size={14} />}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Indexed Emails */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <Mail size={14} className="text-indigo-400" />
            Indexed Emails
            {emailTotal > 0 && (
              <span className="badge bg-surface-700 text-gray-400">{emailTotal}</span>
            )}
          </h2>
          <button onClick={refreshEmails} className="btn-ghost text-xs py-1 px-2">
            {loadingEmails ? <Loader2 size={12} className="animate-spin" /> : 'Refresh'}
          </button>
        </div>

        {/* Email search */}
        <div className="flex gap-2 mb-3">
          <input
            value={emailSearchInput}
            onChange={e => setEmailSearchInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleEmailSearch()}
            placeholder="Search emails by sender, subject…"
            className="input flex-1 text-sm"
          />
          <button onClick={handleEmailSearch} className="btn-ghost flex-shrink-0 px-3">
            <Search size={14} />
          </button>
        </div>

        {emails.length === 0 ? (
          <p className="text-xs text-gray-600 text-center py-6 card">
            {emailSearch ? 'No emails match your search.' : 'No indexed emails yet. Sync emails to index them.'}
          </p>
        ) : (
          <div className="space-y-2">
            {emails.map(doc => (
              <div key={doc.document_id} className="card flex items-center gap-3 py-3">
                <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center flex-shrink-0">
                  <Mail size={14} className="text-indigo-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-200 truncate font-medium">{doc.subject || '(no subject)'}</p>
                  <p className="text-xs text-gray-500 truncate">
                    {doc.sender}
                    {doc.email_account && <span className="ml-1 text-gray-600">· {doc.email_account}</span>}
                  </p>
                  {doc.received_at && (
                    <p className="text-[10px] text-gray-600">{formatDate(doc.received_at)}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(doc.document_id)}
                  disabled={deletingId === doc.document_id}
                  className="p-1.5 rounded-lg text-gray-600 hover:text-red-400 hover:bg-red-900/20 transition-colors disabled:opacity-40"
                  title="Remove from knowledge base"
                >
                  {deletingId === doc.document_id
                    ? <Loader2 size={14} className="animate-spin" />
                    : <Trash2 size={14} />}
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {emailTotal > PAGE_SIZE && (
          <div className="flex items-center justify-center gap-3 mt-3">
            <button
              onClick={() => setEmailPage(p => Math.max(0, p - 1))}
              disabled={emailPage === 0}
              className="btn-ghost p-1.5 disabled:opacity-30"
            >
              <ChevronLeft size={16} />
            </button>
            <span className="text-xs text-gray-500">
              {emailPage + 1} / {totalPages}
            </span>
            <button
              onClick={() => setEmailPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={emailPage >= totalPages - 1}
              className="btn-ghost p-1.5 disabled:opacity-30"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>

      {/* Query */}
      <div>
        <h2 className="text-sm font-medium text-gray-300 mb-2">Query knowledge base</h2>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && search()}
            placeholder="Ask about your documents or emails…"
            className="input flex-1"
          />
          <button onClick={search} disabled={!query.trim() || querying} className="btn-primary flex-shrink-0">
            {querying ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          </button>
        </div>
      </div>

      {queryError && (
        <div className="bg-red-950/40 border border-red-800/50 text-red-400 text-sm px-4 py-3 rounded-lg">
          {queryError}
        </div>
      )}

      {result && <RAGResult result={result} />}
    </div>
  )
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('ro-RO', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function RAGResult({ result }: { result: RAGQueryResponse }) {
  const [showSources, setShowSources] = useState(true)
  return (
    <div className="card space-y-4 animate-slide-up">
      <div>
        <p className="text-xs text-gray-500 mb-2">Answer</p>
        <div className="prose-bob">
          <ReactMarkdown>{result.answer}</ReactMarkdown>
        </div>
      </div>

      {result.sources.length > 0 && (
        <div>
          <button
            onClick={() => setShowSources(v => !v)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            {showSources ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {result.sources.length} source{result.sources.length > 1 ? 's' : ''} cited
          </button>
          {showSources && (
            <div className="mt-2 space-y-2">
              {result.sources.map((s, i) => (
                <div key={i} className="bg-surface-900 border border-surface-700 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="badge bg-indigo-600/20 text-indigo-400 border border-indigo-500/20">
                      Source {i + 1}
                    </span>
                    <span className="text-xs text-gray-400 truncate">{s.source}</span>
                    <span className="badge bg-surface-700 text-gray-500 text-[10px] ml-auto">{s.format}</span>
                  </div>
                  <p className="text-xs text-gray-500 leading-relaxed line-clamp-3">{s.excerpt}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
