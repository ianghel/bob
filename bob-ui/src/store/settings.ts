import { createContext, useContext, useState, useEffect, ReactNode, createElement } from 'react'
import type { Settings } from '../api/client'

const STORAGE_KEY = 'bob_settings'

const defaults: Settings = {
  apiKey: 'dev-secret-key-change-in-prod',
  baseUrl: '',  // empty = use Vite proxy (/api → localhost:8000)
  systemPrompt: 'You are Bob, a helpful AI assistant.',
}

function load(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...defaults, ...JSON.parse(raw) } : defaults
  } catch {
    return defaults
  }
}

interface SettingsCtx {
  settings: Settings
  update: (partial: Partial<Settings>) => void
  reset: () => void
}

const Ctx = createContext<SettingsCtx>({
  settings: defaults,
  update: () => {},
  reset: () => {},
})

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  }, [settings])

  const update = (partial: Partial<Settings>) =>
    setSettings(prev => ({ ...prev, ...partial }))

  const reset = () => setSettings(defaults)

  return createElement(Ctx.Provider, { value: { settings, update, reset } }, children)
}

export function useSettings() {
  return useContext(Ctx)
}
