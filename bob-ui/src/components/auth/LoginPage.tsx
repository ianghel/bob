import { useState, useEffect } from 'react'
import { Loader2, MessageSquare, Mail, FileSearch, Brain, Shield, Zap } from 'lucide-react'
import { useAuth } from '../../store/auth'
import { useSettings } from '../../store/settings'
import { apiLogin, apiRegister } from '../../api/client'

const FEATURES = [
  {
    icon: MessageSquare,
    title: 'Smart Chat',
    desc: 'Have natural conversations powered by advanced AI. Ask anything, get intelligent answers.',
  },
  {
    icon: Mail,
    title: 'Email Integration',
    desc: 'Connect Gmail or work email. Search, read, and send emails directly from chat.',
  },
  {
    icon: FileSearch,
    title: 'Knowledge Base (RAG)',
    desc: 'Upload documents and get instant answers. Bob searches your files so you don\'t have to.',
  },
  {
    icon: Brain,
    title: 'AI Agent Tools',
    desc: 'Bob uses tools to reason and act — web search, calculations, and more.',
  },
  {
    icon: Shield,
    title: 'Multi-Tenant & Secure',
    desc: 'Your data stays isolated. Each account has its own secure workspace.',
  },
  {
    icon: Zap,
    title: 'Free to Use',
    desc: 'Full access to all features. No credit card, no subscription — just sign up and start.',
  },
]

export default function LoginPage() {
  const { login } = useAuth()
  const { settings } = useSettings()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Detect redirect from email verification
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('email_verified') === '1') {
      setSuccess('Email verified successfully! You can now sign in.')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setSuccess(null)

    const baseUrl = settings.baseUrl || ''

    try {
      if (mode === 'register') {
        await apiRegister(baseUrl, email, password, name)
        setSuccess('Registration successful! Please check your email to verify your account.')
        setMode('login')
      } else {
        const data = await apiLogin(baseUrl, email, password)
        await login(data.access_token, data.tenant_slug)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen bg-surface-900">
      {/* Left side — Features */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-center px-12 xl:px-20 bg-gradient-to-br from-indigo-950/60 via-surface-900 to-surface-900 border-r border-surface-700/50">
        <div className="max-w-lg">
          {/* Logo + tagline */}
          <div className="flex items-center gap-3 mb-2">
            <div className="w-11 h-11 rounded-xl bg-indigo-600 flex items-center justify-center font-bold text-white text-lg shrink-0">
              B
            </div>
            <h1 className="text-2xl font-bold text-gray-100">Bob</h1>
          </div>
          <p className="text-indigo-300/80 text-sm mb-10 ml-14">Your AI assistant — free to use</p>

          {/* Feature grid */}
          <div className="grid grid-cols-1 gap-5">
            {FEATURES.map((f) => (
              <div key={f.title} className="flex gap-3.5 items-start">
                <div className="w-9 h-9 rounded-lg bg-indigo-600/15 flex items-center justify-center shrink-0 mt-0.5">
                  <f.icon size={18} className="text-indigo-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-200">{f.title}</h3>
                  <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-10 pt-6 border-t border-surface-700/40">
            <p className="text-[11px] text-gray-600">
              Built by{' '}
              <a href="https://teninvent.ro" target="_blank" rel="noopener" className="text-indigo-500 hover:text-indigo-400 transition-colors">
                Ten Invent
              </a>
            </p>
          </div>
        </div>
      </div>

      {/* Right side — Login form */}
      <div className="flex w-full lg:w-1/2 items-center justify-center px-6">
        <div className="w-full max-w-sm">
          {/* Mobile logo (shown only on small screens) */}
          <div className="text-center mb-8 lg:hidden">
            <div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center font-bold text-white text-2xl mx-auto mb-3">
              B
            </div>
            <h1 className="text-xl font-semibold text-gray-100">Welcome to Bob</h1>
            <p className="text-sm text-gray-500 mt-1">Your AI assistant — free to use</p>
          </div>

          {/* Desktop heading */}
          <div className="hidden lg:block text-center mb-8">
            <h2 className="text-xl font-semibold text-gray-100">
              {mode === 'login' ? 'Welcome back' : 'Create your account'}
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              {mode === 'login' ? 'Sign in to continue to Bob' : 'Get started for free'}
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="card space-y-4">
            {mode === 'register' && (
              <div>
                <label className="text-xs text-gray-400 mb-1.5 block">Name</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Your name"
                  className="input"
                  required
                />
              </div>
            )}

            <div>
              <label className="text-xs text-gray-400 mb-1.5 block">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="input"
                required
              />
            </div>

            <div>
              <label className="text-xs text-gray-400 mb-1.5 block">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="Min. 8 characters"
                className="input"
                minLength={8}
                required
              />
            </div>

            {error && (
              <div className="bg-red-950/40 border border-red-800/50 text-red-400 text-xs px-3 py-2 rounded-lg">
                {error}
              </div>
            )}

            {success && (
              <div className="bg-emerald-950/40 border border-emerald-800/50 text-emerald-400 text-xs px-3 py-2 rounded-lg">
                {success}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-2.5">
              {loading && <Loader2 size={14} className="animate-spin" />}
              {mode === 'login' ? 'Sign in' : 'Create account'}
            </button>

            <p className="text-xs text-gray-500 text-center">
              {mode === 'login' ? (
                <>
                  Don't have an account?{' '}
                  <button type="button" onClick={() => { setMode('register'); setError(null); setSuccess(null) }} className="text-indigo-400 hover:underline">
                    Register
                  </button>
                </>
              ) : (
                <>
                  Already have an account?{' '}
                  <button type="button" onClick={() => { setMode('login'); setError(null); setSuccess(null) }} className="text-indigo-400 hover:underline">
                    Sign in
                  </button>
                </>
              )}
            </p>
          </form>
        </div>
      </div>
    </div>
  )
}
