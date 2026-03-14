import { useState, useRef, useEffect, useCallback } from 'react'
import { Plus, Trash2, ChevronRight, Send, Square, PanelLeft, X, BookOpen, Archive, Paperclip, Mic, MicOff, Volume2, VolumeX, Settings2 } from 'lucide-react'
import { clsx } from 'clsx'
import ReactMarkdown from 'react-markdown'
import { useSettings } from '../../store/settings'
import { useAuth } from '../../store/auth'
import { sendChat, streamChat, getHistory, deleteSession, listSessions, archiveSession, uploadChatFile, transcribeAudio } from '../../api/client'
import type { ChatMessage, AuthHeaders, SessionSummary } from '../../api/client'

interface Session {
  id: string
  title: string
  messages: ChatMessage[]
  loaded: boolean // whether messages have been fetched from server
}

function newSession(): Session {
  return { id: crypto.randomUUID(), title: 'New chat', messages: [], loaded: true }
}

export default function ChatPanel() {
  const { settings } = useSettings()
  const { auth } = useAuth()
  const authHeaders: AuthHeaders = { token: auth.token!, tenantSlug: auth.tenantSlug! }
  const [sessions, setSessions] = useState<Session[]>([newSession()])
  const [activeId, setActiveId] = useState<string>(sessions[0].id)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [showSessions, setShowSessions] = useState(false)
  const [useKnowledge, setUseKnowledge] = useState(true)
  const abortRef = useRef<boolean>(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  // TTS voice selection
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [selectedVoiceURI, setSelectedVoiceURI] = useState<string>(
    () => localStorage.getItem('bob-tts-voice') || ''
  )
  const [showVoiceMenu, setShowVoiceMenu] = useState(false)

  // Load available voices
  useEffect(() => {
    const loadVoices = () => {
      const v = window.speechSynthesis.getVoices()
      if (v.length > 0) setVoices(v)
    }
    loadVoices()
    window.speechSynthesis.addEventListener('voiceschanged', loadVoices)
    return () => window.speechSynthesis.removeEventListener('voiceschanged', loadVoices)
  }, [])

  const setVoice = (uri: string) => {
    setSelectedVoiceURI(uri)
    localStorage.setItem('bob-tts-voice', uri)
    setShowVoiceMenu(false)
  }

  const selectedVoice = voices.find(v => v.voiceURI === selectedVoiceURI) || null

  const active = sessions.find(s => s.id === activeId)!
  const containerRef = useRef<HTMLDivElement>(null)
  const [viewportHeight, setViewportHeight] = useState<number | null>(null)

  // Load sessions from server on mount
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const serverSessions = await listSessions(settings, authHeaders)
        if (cancelled) return
        if (serverSessions.length > 0) {
          const loaded: Session[] = serverSessions.map((s: SessionSummary) => ({
            id: s.session_id,
            title: s.title || 'Untitled',
            messages: [],
            loaded: false,
          }))
          // Prepend a fresh "New chat" session
          const fresh = newSession()
          setSessions([fresh, ...loaded])
          setActiveId(fresh.id)
        }
      } catch {
        // Silently fail — keep the default local session
      }
    })()
    return () => { cancelled = true }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Handle mobile visual viewport resize (keyboard open/close)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const onResize = () => {
      const keyboardOpen = vv.height < window.innerHeight * 0.85
      setViewportHeight(keyboardOpen ? vv.height : null)
    }
    vv.addEventListener('resize', onResize)
    return () => {
      vv.removeEventListener('resize', onResize)
    }
  }, [])

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [active?.messages, streamingContent])

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [input])

  const updateSession = useCallback((id: string, updater: (s: Session) => Session) => {
    setSessions(prev => prev.map(s => s.id === id ? updater(s) : s))
  }, [])

  const selectSession = async (id: string) => {
    setActiveId(id)
    setShowSessions(false)

    // Load messages from server if not yet loaded
    const session = sessions.find(s => s.id === id)
    if (session && !session.loaded) {
      try {
        const history = await getHistory(id, settings, authHeaders)
        const msgs: ChatMessage[] = []
        for (const turn of history.turns) {
          msgs.push({ role: 'user', content: turn.user })
          msgs.push({ role: 'assistant', content: turn.assistant })
        }
        setSessions(prev => prev.map(s =>
          s.id === id ? { ...s, messages: msgs, loaded: true } : s
        ))
      } catch {
        // Failed to load — mark as loaded to avoid retrying
        setSessions(prev => prev.map(s =>
          s.id === id ? { ...s, loaded: true } : s
        ))
      }
    }
  }

  const send = async () => {
    if (!input.trim() || loading) return
    const userMsg = input.trim()
    setInput('')
    setError(null)
    textareaRef.current?.blur()

    // Optimistically add user message
    const userChatMsg: ChatMessage = { role: 'user', content: userMsg }
    updateSession(activeId, s => ({
      ...s,
      title: s.messages.length === 0 ? userMsg.slice(0, 36) + (userMsg.length > 36 ? '…' : '') : s.title,
      messages: [...s.messages, userChatMsg],
    }))

    setLoading(true)
    abortRef.current = false

    try {
      setStreaming(true)
      setStreamingContent('')
      let full = ''
      let finalSessionId = activeId

      for await (const event of streamChat(userMsg, activeId, settings, authHeaders, useKnowledge)) {
        if (abortRef.current) break
        if (event.error) { setError(event.error); break }
        if (event.session_id) finalSessionId = event.session_id
        if (event.chunk) {
          full += event.chunk
          setStreamingContent(full)
        }
        if (event.done) break
      }

      if (full) {
        const assistantMsg: ChatMessage = { role: 'assistant', content: full }
        updateSession(activeId, s => ({
          ...s,
          id: finalSessionId !== activeId ? finalSessionId : s.id,
          messages: [...s.messages, assistantMsg],
        }))
        // If session ID changed (first message), update active
        if (finalSessionId !== activeId) {
          setSessions(prev => prev.map(s =>
            s.id === activeId ? { ...s, id: finalSessionId } : s
          ))
          setActiveId(finalSessionId)
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Unknown error'
      setError(msg)
      updateSession(activeId, s => ({
        ...s,
        messages: s.messages.slice(0, -1),
      }))
      setInput(userMsg)
    } finally {
      setLoading(false)
      setStreaming(false)
      setStreamingContent('')
    }
  }

  const stopStreaming = () => { abortRef.current = true }

  const createSession = () => {
    const s = newSession()
    setSessions(prev => [s, ...prev])
    setActiveId(s.id)
    setShowSessions(false)
  }

  const removeSession = async (id: string) => {
    try { await deleteSession(id, settings, authHeaders) } catch { /* ignore */ }
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id)
      if (next.length === 0) {
        const fresh = newSession()
        setActiveId(fresh.id)
        return [fresh]
      }
      if (activeId === id) setActiveId(next[0].id)
      return next
    })
  }

  const handleArchive = async (id: string) => {
    try {
      const result = await archiveSession(id, settings, authHeaders)
      setError(null)
      // Show brief success feedback via error slot (reuse for simplicity)
      setError(`Archived: ${result.message}`)
      setTimeout(() => setError(null), 3000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Archive failed')
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = '' // reset so same file can be re-uploaded

    setError(null)
    setUploading(true)

    // Show user message about the upload
    const userMsg = input.trim() || `Uploaded: ${file.name}`
    const userChatMsg: ChatMessage = { role: 'user', content: `📎 ${userMsg}` }
    updateSession(activeId, s => ({
      ...s,
      title: s.messages.length === 0 ? file.name.slice(0, 36) : s.title,
      messages: [...s.messages, userChatMsg],
    }))
    setInput('')

    try {
      const result = await uploadChatFile(file, activeId, input.trim(), settings, authHeaders)
      const savedNote = `> **${result.filename}** saved to Bob's memory (${result.chunks} chunks)\n\n`
      const assistantMsg: ChatMessage = { role: 'assistant', content: savedNote + result.content }
      updateSession(activeId, s => ({
        ...s,
        id: result.session_id !== activeId ? result.session_id : s.id,
        messages: [...s.messages, assistantMsg],
      }))
      if (result.session_id !== activeId) {
        setSessions(prev => prev.map(s =>
          s.id === activeId ? { ...s, id: result.session_id } : s
        ))
        setActiveId(result.session_id)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      setError(msg)
    } finally {
      setUploading(false)
    }
  }

  const toggleRecording = async () => {
    if (recording) {
      // Stop recording
      mediaRecorderRef.current?.stop()
      setRecording(false)
      return
    }

    // Start recording
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })
      mediaRecorderRef.current = mediaRecorder
      chunksRef.current = []

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      mediaRecorder.onstop = async () => {
        // Stop all tracks to release the mic
        stream.getTracks().forEach(t => t.stop())

        const audioBlob = new Blob(chunksRef.current, { type: 'audio/webm' })
        if (audioBlob.size < 100) return // too short, ignore

        setTranscribing(true)
        try {
          const text = await transcribeAudio(audioBlob, settings, authHeaders)
          if (text.trim()) {
            setInput(text.trim())
            // Auto-focus textarea so user can review or send
            textareaRef.current?.focus()
          }
        } catch (err: unknown) {
          setError(err instanceof Error ? err.message : 'Transcription failed')
        } finally {
          setTranscribing(false)
        }
      }

      mediaRecorder.start()
      setRecording(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Microphone access denied')
    }
  }

  return (
    <div
      ref={containerRef}
      className="flex h-full relative"
      style={viewportHeight ? { height: `${viewportHeight}px` } : undefined}
    >
      {/* Mobile overlay backdrop */}
      {showSessions && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-20"
          onClick={() => setShowSessions(false)}
        />
      )}

      {/* Session list — desktop: static sidebar, mobile: slide-over drawer */}
      <aside
        className={clsx(
          'flex-shrink-0 border-r border-surface-700 flex flex-col bg-surface-900/95 backdrop-blur-sm',
          'hidden md:flex w-52',
          showSessions && '!flex fixed inset-y-0 left-0 w-64 z-30',
        )}
      >
        <div className="p-2 border-b border-surface-700 flex items-center gap-1">
          <button onClick={createSession} className="btn-primary flex-1 justify-center text-xs py-2">
            <Plus size={14} /> New chat
          </button>
          <button
            onClick={() => setShowSessions(false)}
            className="md:hidden p-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-surface-700"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-1 space-y-0.5">
          {sessions.map(s => (
            <div
              key={s.id}
              onClick={() => selectSession(s.id)}
              className={clsx(
                'group flex items-center gap-1 px-2 py-2 rounded-lg cursor-pointer transition-colors',
                activeId === s.id
                  ? 'bg-surface-700 text-gray-100'
                  : 'text-gray-400 hover:bg-surface-800 hover:text-gray-200',
              )}
            >
              <ChevronRight size={12} className={clsx('flex-shrink-0 transition-transform', activeId === s.id && 'rotate-90')} />
              <span className="flex-1 text-xs truncate">{s.title}</span>
              {s.messages.length > 0 && (
                <button
                  onClick={e => { e.stopPropagation(); handleArchive(s.id) }}
                  className="opacity-0 group-hover:opacity-100 md:opacity-0 p-0.5 hover:text-indigo-400 transition-all"
                  title="Archive to knowledge base"
                >
                  <Archive size={11} />
                </button>
              )}
              <button
                onClick={e => { e.stopPropagation(); removeSession(s.id) }}
                className="flex-shrink-0 p-0.5 hover:text-red-400 transition-all text-gray-600 md:opacity-0 md:group-hover:opacity-100"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-3 md:px-4 py-4 md:py-6 space-y-4 md:space-y-6">
          {active.messages.length === 0 && !streaming && (
            <div className="flex flex-col items-center justify-center h-full text-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center">
                <span className="text-2xl font-bold text-indigo-400">B</span>
              </div>
              <div>
                <p className="text-gray-300 font-medium">Hi, I'm Bob</p>
                <p className="text-gray-500 text-sm mt-1">How can I help you today?</p>
              </div>
            </div>
          )}

          {active.messages.map((msg, i) => (
            <MessageBubble key={i} message={msg} voice={selectedVoice} />
          ))}

          {streaming && streamingContent && (
            <MessageBubble
              message={{ role: 'assistant', content: streamingContent }}
              streaming
              voice={selectedVoice}
            />
          )}

          {error && (
            <div className="flex justify-center">
              <div className={clsx(
                'text-xs px-4 py-2 rounded-lg max-w-md text-center border',
                error.startsWith('Archived:')
                  ? 'bg-green-950/40 border-green-800/50 text-green-400'
                  : 'bg-red-950/40 border-red-800/50 text-red-400',
              )}>
                {error}
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-surface-700 p-2 md:p-4">
          {/* Textarea + Send row */}
          <div className="flex gap-2 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={transcribing ? 'Transcribing audio…' : uploading ? 'Uploading file…' : recording ? 'Recording… click mic to stop' : useKnowledge ? 'Message Bob (knowledge base active)…' : 'Message Bob…'}
              rows={1}
              className="input flex-1 resize-none leading-relaxed"
              style={{ minHeight: '44px' }}
            />
            {streaming ? (
              <button onClick={stopStreaming} className="btn bg-red-900/40 hover:bg-red-800/50 text-red-400 flex-shrink-0 h-11">
                <Square size={16} />
              </button>
            ) : (
              <button
                onClick={send}
                disabled={!input.trim() || loading}
                className="btn-primary flex-shrink-0 h-11"
              >
                <Send size={16} />
              </button>
            )}
          </div>

          {/* Toolbar row — under the textarea */}
          <div className="flex gap-1 items-center mt-2">
            {/* Mobile session toggle */}
            <button
              onClick={() => setShowSessions(v => !v)}
              className="md:hidden flex-shrink-0 p-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-surface-700 transition-colors"
              title="Chat sessions"
            >
              <PanelLeft size={16} />
            </button>
            {/* Knowledge base toggle */}
            <button
              onClick={() => setUseKnowledge(v => !v)}
              className={clsx(
                'flex-shrink-0 p-2 rounded-lg transition-colors',
                useKnowledge
                  ? 'text-indigo-400 bg-indigo-600/20 border border-indigo-500/30'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-surface-700',
              )}
              title={useKnowledge ? 'Knowledge base: ON' : 'Knowledge base: OFF'}
            >
              <BookOpen size={16} />
            </button>
            {/* File upload */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.docx"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading || loading}
              className="flex-shrink-0 p-2 rounded-lg transition-colors text-gray-400 hover:text-gray-200 hover:bg-surface-700 disabled:opacity-40"
              title="Upload file to Bob's memory (PDF, TXT, MD, DOCX)"
            >
              <Paperclip size={16} />
            </button>
            {/* Voice recording */}
            <button
              onClick={toggleRecording}
              disabled={transcribing || loading}
              className={clsx(
                'flex-shrink-0 p-2 rounded-lg transition-colors disabled:opacity-40',
                recording
                  ? 'text-red-400 bg-red-600/20 border border-red-500/30 animate-pulse'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-surface-700',
              )}
              title={recording ? 'Stop recording' : transcribing ? 'Transcribing…' : 'Voice input'}
            >
              {recording ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
            {/* TTS voice picker */}
            <div className="relative flex-shrink-0">
              <button
                onClick={() => setShowVoiceMenu(v => !v)}
                className={clsx(
                  'p-2 rounded-lg transition-colors',
                  selectedVoice
                    ? 'text-indigo-400 bg-indigo-600/20 border border-indigo-500/30'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-surface-700',
                )}
                title={selectedVoice ? `TTS: ${selectedVoice.name}` : 'Select TTS voice'}
              >
                <Volume2 size={16} />
              </button>
              {showVoiceMenu && (
                <div className="absolute bottom-full left-0 mb-2 w-72 max-h-64 overflow-y-auto rounded-xl bg-surface-800 border border-surface-600 shadow-xl z-50">
                  <div className="p-2 border-b border-surface-700 text-xs text-gray-400 font-medium">
                    Select voice for TTS
                  </div>
                  <button
                    onClick={() => setVoice('')}
                    className={clsx(
                      'w-full text-left px-3 py-2 text-xs hover:bg-surface-700 transition-colors',
                      !selectedVoiceURI ? 'text-indigo-400 bg-surface-700/50' : 'text-gray-300',
                    )}
                  >
                    Auto (browser default)
                  </button>
                  {voices.map(v => (
                    <button
                      key={v.voiceURI}
                      onClick={() => setVoice(v.voiceURI)}
                      className={clsx(
                        'w-full text-left px-3 py-2 text-xs hover:bg-surface-700 transition-colors flex items-center gap-2',
                        selectedVoiceURI === v.voiceURI ? 'text-indigo-400 bg-surface-700/50' : 'text-gray-300',
                      )}
                    >
                      <span className="flex-1 truncate">{v.name}</span>
                      <span className="text-[10px] text-gray-500 flex-shrink-0">{v.lang}</span>
                    </button>
                  ))}
                  {voices.length === 0 && (
                    <p className="px-3 py-2 text-xs text-gray-500">No voices available</p>
                  )}
                </div>
              )}
            </div>

            {/* Spacer + session info (desktop) */}
            <div className="flex-1" />
            <p className="hidden md:block text-xs text-gray-600 text-right">
              Session: <span className="font-mono">{activeId.slice(0, 8)}…</span>
              {useKnowledge && <span className="ml-2 text-indigo-500">KB active</span>}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message, streaming, voice }: { message: ChatMessage; streaming?: boolean; voice?: SpeechSynthesisVoice | null }) {
  const isUser = message.role === 'user'
  const [speaking, setSpeaking] = useState(false)

  const toggleSpeak = () => {
    if (speaking) {
      window.speechSynthesis.cancel()
      setSpeaking(false)
      return
    }

    // Strip markdown for cleaner speech
    const plainText = message.content
      .replace(/```[\s\S]*?```/g, '') // code blocks
      .replace(/`[^`]*`/g, '')       // inline code
      .replace(/[#*_~>\[\]()!|-]/g, '') // markdown symbols
      .replace(/\n{2,}/g, '. ')      // paragraph breaks → pause
      .replace(/\n/g, ' ')
      .trim()

    if (!plainText) return

    const utterance = new SpeechSynthesisUtterance(plainText)
    utterance.rate = 1.0
    utterance.pitch = 1.0

    if (voice) {
      utterance.voice = voice
      utterance.lang = voice.lang
    } else {
      // Fallback: try Romanian voice
      utterance.lang = 'ro-RO'
      const allVoices = window.speechSynthesis.getVoices()
      const roVoice = allVoices.find(v => v.lang.startsWith('ro'))
      if (roVoice) utterance.voice = roVoice
    }

    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)

    window.speechSynthesis.speak(utterance)
    setSpeaking(true)
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (speaking) window.speechSynthesis.cancel()
    }
  }, [speaking])

  return (
    <div className={clsx('flex gap-2 md:gap-3 animate-slide-up', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div className={clsx(
        'w-7 h-7 rounded-lg flex-shrink-0 flex items-center justify-center text-xs font-bold mt-0.5',
        isUser ? 'bg-indigo-600 text-white' : 'bg-surface-700 text-indigo-400 border border-surface-600',
      )}>
        {isUser ? 'U' : 'B'}
      </div>

      {/* Bubble */}
      <div className={clsx(
        'max-w-[85%] md:max-w-[75%] rounded-2xl px-3 md:px-4 py-2.5 md:py-3',
        isUser
          ? 'bg-indigo-600/20 border border-indigo-500/30 rounded-tr-sm'
          : 'bg-surface-800 border border-surface-700 rounded-tl-sm',
      )}>
        {isUser ? (
          <p className="text-sm text-gray-200 whitespace-pre-wrap">{message.content}</p>
        ) : (
          <>
            <div className="prose-bob">
              <ReactMarkdown>{message.content}</ReactMarkdown>
              {streaming && <span className="inline-block w-1.5 h-4 bg-indigo-400 ml-0.5 animate-blink rounded-sm" />}
            </div>
            {!streaming && message.content && (
              <button
                onClick={toggleSpeak}
                className={clsx(
                  'mt-2 p-1 rounded transition-colors',
                  speaking
                    ? 'text-indigo-400 hover:text-indigo-300'
                    : 'text-gray-600 hover:text-gray-400',
                )}
                title={speaking ? 'Stop speaking' : 'Read aloud'}
              >
                {speaking ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
