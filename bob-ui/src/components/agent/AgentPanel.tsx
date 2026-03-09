import { useState } from 'react'
import { Bot, Play, Clock, CheckCircle2, XCircle, Wrench, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import ReactMarkdown from 'react-markdown'
import { useSettings } from '../../store/settings'
import { useAuth } from '../../store/auth'
import { runAgent } from '../../api/client'
import type { AgentRunResponse, ToolCall, AuthHeaders } from '../../api/client'

const EXAMPLE_TASKS = [
  'What is 15% of 4200? Show the calculation.',
  'What time is it right now?',
  'Calculate the compound interest on $10,000 at 5% annually for 3 years.',
  'Search the knowledge base for information about NovaTech AI.',
]

export default function AgentPanel() {
  const { settings } = useSettings()
  const { auth } = useAuth()
  const authHeaders: AuthHeaders = { token: auth.token!, tenantSlug: auth.tenantSlug! }
  const [task, setTask] = useState('')
  const [running, setRunning] = useState(false)
  const [runs, setRuns] = useState<AgentRunResponse[]>([])
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!task.trim() || running) return
    setRunning(true)
    setError(null)
    try {
      const result = await runAgent(task.trim(), settings, authHeaders)
      setRuns(prev => [result, ...prev])
      setTask('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Agent run failed')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 space-y-4 md:space-y-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-emerald-600/20 border border-emerald-500/30 flex items-center justify-center">
          <Bot size={18} className="text-emerald-400" />
        </div>
        <div>
          <h1 className="text-base font-semibold text-gray-100">Agent Runner</h1>
          <p className="text-xs text-gray-500">Bob will choose tools autonomously to complete your task</p>
        </div>
      </div>

      {/* Tools available */}
      <div className="flex flex-wrap gap-2">
        {['calculator', 'get_current_time', 'summarize_text', 'rag_lookup'].map(t => (
          <span key={t} className="badge bg-surface-700 text-gray-400 border border-surface-600 font-mono text-[11px]">
            <Wrench size={10} /> {t}
          </span>
        ))}
      </div>

      {/* Task input */}
      <div className="space-y-2">
        <textarea
          value={task}
          onChange={e => setTask(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && e.ctrlKey && run()}
          placeholder="Describe a task for Bob to complete… (Ctrl+Enter to run)"
          rows={3}
          className="input resize-none"
        />
        <div className="flex items-center justify-between">
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_TASKS.map(ex => (
              <button
                key={ex}
                onClick={() => setTask(ex)}
                className="text-[11px] px-2 py-1 rounded bg-surface-700 hover:bg-surface-600 text-gray-400 hover:text-gray-200 transition-colors"
              >
                {ex.slice(0, 38)}…
              </button>
            ))}
          </div>
          <button onClick={run} disabled={!task.trim() || running} className="btn-primary flex-shrink-0">
            {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            {running ? 'Running…' : 'Run'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800/50 text-red-400 text-sm px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      {/* Run history */}
      {runs.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-gray-300">Run history</h2>
          {runs.map(run => (
            <RunCard key={run.run_id} run={run} />
          ))}
        </div>
      )}

      {runs.length === 0 && !running && (
        <div className="text-center py-12 text-gray-600">
          <Bot size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No runs yet. Give Bob a task above.</p>
        </div>
      )}
    </div>
  )
}

function RunCard({ run }: { run: AgentRunResponse }) {
  const [expanded, setExpanded] = useState(true)

  const statusIcon = {
    completed: <CheckCircle2 size={14} className="text-emerald-400" />,
    failed: <XCircle size={14} className="text-red-400" />,
    running: <Loader2 size={14} className="text-indigo-400 animate-spin" />,
    pending: <Clock size={14} className="text-gray-400" />,
  }[run.status]

  const statusColor = {
    completed: 'text-emerald-400',
    failed: 'text-red-400',
    running: 'text-indigo-400',
    pending: 'text-gray-400',
  }[run.status]

  return (
    <div className="card space-y-3 animate-slide-up">
      {/* Header */}
      <div className="flex items-start gap-2">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          {statusIcon}
          <span className={clsx('text-xs font-medium', statusColor)}>{run.status}</span>
          <span className="text-gray-600 text-xs">·</span>
          <span className="text-xs text-gray-500 font-mono truncate">{run.run_id.slice(0, 8)}</span>
          {run.duration_seconds && (
            <>
              <span className="text-gray-600 text-xs">·</span>
              <span className="text-xs text-gray-500">{run.duration_seconds.toFixed(1)}s</span>
            </>
          )}
        </div>
        <button onClick={() => setExpanded(v => !v)} className="btn-ghost p-1 text-gray-500">
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      {/* Task */}
      <div className="bg-surface-900 rounded-lg px-3 py-2">
        <p className="text-xs text-gray-500 mb-0.5">Task</p>
        <p className="text-sm text-gray-200">{run.task}</p>
      </div>

      {expanded && (
        <>
          {/* Tool calls */}
          {run.tool_calls.length > 0 && (
            <div>
              <p className="text-xs text-gray-500 mb-2">Tools used ({run.tool_calls.length})</p>
              <div className="space-y-1.5">
                {run.tool_calls.map((tc, i) => (
                  <ToolCallCard key={i} tc={tc} />
                ))}
              </div>
            </div>
          )}

          {/* Output */}
          {run.output && (
            <div>
              <p className="text-xs text-gray-500 mb-1.5">Output</p>
              <div className="prose-bob bg-surface-900 rounded-lg px-3 py-2.5">
                <ReactMarkdown>{run.output}</ReactMarkdown>
              </div>
            </div>
          )}

          {run.error && (
            <div className="bg-red-950/30 border border-red-800/40 rounded-lg px-3 py-2 text-xs text-red-400">
              {run.error}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ToolCallCard({ tc }: { tc: ToolCall }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="bg-surface-900 border border-surface-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-surface-800 transition-colors text-left"
      >
        <Wrench size={12} className="text-amber-400 flex-shrink-0" />
        <span className="text-xs font-mono text-amber-300 font-medium">{tc.tool_name}</span>
        <span className="text-xs text-gray-500 truncate flex-1">
          {Object.values(tc.input).join(', ').slice(0, 60)}
        </span>
        <span className="text-[10px] text-gray-600">{tc.duration_ms.toFixed(1)}ms</span>
        {open ? <ChevronUp size={11} className="text-gray-500" /> : <ChevronDown size={11} className="text-gray-500" />}
      </button>
      {open && (
        <div className="px-3 pb-2.5 space-y-1.5 border-t border-surface-700 pt-2">
          <div>
            <p className="text-[10px] text-gray-600 mb-1">Input</p>
            <pre className="text-[11px] text-gray-300 bg-surface-800 rounded p-2 overflow-x-auto">
              {JSON.stringify(tc.input, null, 2)}
            </pre>
          </div>
          <div>
            <p className="text-[10px] text-gray-600 mb-1">Output</p>
            <pre className="text-[11px] text-emerald-400 bg-surface-800 rounded p-2 overflow-x-auto whitespace-pre-wrap">
              {tc.output}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
