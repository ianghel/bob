import { useState, useEffect } from 'react'
import { MessageSquare, BookOpen, Mail, Settings, Wifi, WifiOff, LogOut } from 'lucide-react'
import { clsx } from 'clsx'
import { useSettings } from './store/settings'
import { useAuth } from './store/auth'
import { healthCheck } from './api/client'
import ChatPanel from './components/chat/ChatPanel'
import RAGPanel from './components/rag/RAGPanel'
import SettingsPanel from './components/settings/SettingsPanel'
import EmailPanel from './components/email/EmailPanel'
import LoginPage from './components/auth/LoginPage'

type Tab = 'chat' | 'rag' | 'email' | 'settings'

const TABS = [
  { id: 'chat' as Tab, label: 'Chat', icon: MessageSquare },
  { id: 'rag' as Tab, label: 'Knowledge', icon: BookOpen },
  { id: 'email' as Tab, label: 'Email', icon: Mail },
  { id: 'settings' as Tab, label: 'Settings', icon: Settings },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('chat')
  const [online, setOnline] = useState<boolean | null>(null)
  const { settings } = useSettings()
  const { isAuthenticated, auth, logout } = useAuth()

  useEffect(() => {
    const check = () =>
      healthCheck(settings.baseUrl || '').then(setOnline)
    check()
    const id = setInterval(check, 15_000)
    return () => clearInterval(id)
  }, [settings.baseUrl])

  if (!isAuthenticated) {
    return <LoginPage />
  }

  return (
    <div className="flex h-[100dvh] overflow-hidden">
      {/* ── Desktop Sidebar (hidden on mobile) ──────────────── */}
      <aside className="hidden md:flex w-56 flex-shrink-0 bg-surface-900 border-r border-surface-700 flex-col">
        {/* Logo */}
        <div className="px-4 py-5 border-b border-surface-700">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white text-sm">
              B
            </div>
            <div>
              <p className="font-semibold text-gray-100 text-sm leading-tight">Bob</p>
              <p className="text-xs text-gray-500 leading-tight">AI Agent</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-2 space-y-0.5">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={clsx(
                'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                tab === id
                  ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-surface-700',
              )}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>

        {/* User + Logout */}
        <div className="px-3 py-3 border-t border-surface-700 space-y-2">
          <div className="flex items-center gap-2 px-1">
            <div className="w-7 h-7 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-xs font-bold text-indigo-400 flex-shrink-0">
              {auth.user?.name?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-gray-200 truncate">{auth.user?.name}</p>
              <p className="text-[10px] text-gray-500 truncate">{auth.user?.email}</p>
            </div>
          </div>
          <button
            onClick={logout}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-gray-400 hover:text-red-400 hover:bg-red-900/20 transition-colors"
          >
            <LogOut size={13} />
            Sign out
          </button>
        </div>

        {/* Status */}
        <div className="px-4 py-3 border-t border-surface-700">
          <div className="flex items-center gap-2 text-xs">
            {online === null ? (
              <span className="text-gray-500">Connecting…</span>
            ) : online ? (
              <>
                <Wifi size={12} className="text-emerald-400" />
                <span className="text-emerald-400">API connected</span>
              </>
            ) : (
              <>
                <WifiOff size={12} className="text-red-400" />
                <span className="text-red-400">API offline</span>
              </>
            )}
          </div>
        </div>
      </aside>

      {/* ── Main content ───────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <div className="flex-1 overflow-hidden">
          {tab === 'chat' && <ChatPanel />}
          {tab === 'rag' && <RAGPanel />}
          {tab === 'email' && <EmailPanel />}
          {tab === 'settings' && <SettingsPanel />}
        </div>

        {/* ── Mobile bottom tab bar ──────────────────────── */}
        <nav className="md:hidden flex-shrink-0 flex border-t border-surface-700 bg-surface-900 pb-[env(safe-area-inset-bottom)]">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={clsx(
                'flex-1 flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors',
                tab === id
                  ? 'text-indigo-400'
                  : 'text-gray-500 active:text-gray-300',
              )}
            >
              <Icon size={20} />
              {label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  )
}
