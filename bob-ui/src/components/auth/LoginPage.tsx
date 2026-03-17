import { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../../store/auth'
import { useSettings } from '../../store/settings'
import { apiLogin, apiRegister } from '../../api/client'

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
    <div className="flex h-screen items-center justify-center bg-surface-900">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center font-bold text-white text-2xl mx-auto mb-3">
            B
          </div>
          <h1 className="text-xl font-semibold text-gray-100">Welcome to Bob</h1>
          <p className="text-sm text-gray-500 mt-1">Sign in to your account</p>
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
  )
}
