import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { GoogleOAuthProvider, GoogleLogin } from '@react-oauth/google'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import DarkToggle from '../components/DarkToggle'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useDarkMode } from '../hooks/useDarkMode'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { setUser } = useAuth()
  const { isDark, toggle } = useDarkMode()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const [googleClientId, setGoogleClientId] = useState<string | null>(null)
  const [tempToken, setTempToken] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const totpRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.getAuthConfig().then(c => {
      if (c.google_client_id) setGoogleClientId(c.google_client_id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (tempToken) setTimeout(() => totpRef.current?.focus(), 50)
  }, [tempToken])

  const onLoginSuccess = (token: string, username: string, role: string) => {
    localStorage.setItem('token', token)
    setUser({ username, role })
    const next = new URLSearchParams(location.search).get('next')
    navigate(next && next.startsWith('/') ? next : '/', { replace: true })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) return
    setLoading(true); setError(null)
    try {
      const res = await api.login(username.trim(), password)
      if (res.requires_totp && res.temp_token) {
        setTempToken(res.temp_token)
      } else if (res.token) {
        onLoginSuccess(res.token, res.username!, res.role!)
      }
    } catch (e: any) {
      setError(e.message || '登入失敗')
    } finally {
      setLoading(false)
    }
  }

  const handleTotpChange = async (value: string) => {
    const digits = value.replace(/\D/g, '').slice(0, 6)
    setTotpCode(digits)
    if (digits.length === 6 && tempToken) {
      setLoading(true); setError(null)
      try {
        const res = await api.totpVerifyLogin(digits, tempToken)
        onLoginSuccess(res.token, res.username, res.role)
      } catch (e: any) {
        setError(e.message || '驗證碼錯誤')
        setTotpCode('')
      } finally {
        setLoading(false)
      }
    }
  }

  const handleGoogleSuccess = async (credentialResponse: { credential?: string }) => {
    if (!credentialResponse.credential) return
    setError(null)
    try {
      const res = await api.googleLogin(credentialResponse.credential)
      if (res.requires_totp && res.temp_token) {
        setTempToken(res.temp_token)
      } else {
        onLoginSuccess(res.token, res.username, res.role)
      }
    } catch (e: any) {
      setError(e.message || 'Google 登入失敗')
    }
  }

  return (
    <div className="login-workspace min-h-screen flex items-center justify-center px-5 py-20">
      <div className="absolute top-4 right-4">
        <DarkToggle isDark={isDark} toggle={toggle} />
      </div>

      <div className="w-full max-w-[420px]">
        <div className="text-center mb-8">
          <img src="/favicon.svg" alt="" width="52" height="52" className="mx-auto mb-5" />
          <h1 className="text-2xl font-semibold text-foreground tracking-tight">標注複查平台</h1>
          <p className="text-sm text-muted-foreground mt-2">請登入以繼續</p>
        </div>

        <div className="login-panel p-7 sm:p-8 space-y-6">

          {!tempToken ? (
            <>
              <form onSubmit={handleSubmit} className="space-y-5">
                <div>
                  <label htmlFor="username" className="block text-sm font-medium mb-2">帳號</label>
                  <Input id="username" autoComplete="username" type="text" value={username} onChange={e => setUsername(e.target.value)}
                    placeholder="輸入帳號" autoFocus
                    className="h-11" />
                </div>
                <div>
                  <label htmlFor="password" className="block text-sm font-medium mb-2">密碼</label>
                  <Input id="password" autoComplete="current-password" type="password" value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="輸入密碼"
                    className="h-11" />
                </div>
                <Button type="submit" disabled={!username.trim() || !password || loading}
                  className="w-full h-11 mt-1">
                  {loading ? '驗證中…' : '登入'}
                </Button>
              </form>

              {googleClientId && (
                <>
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-px bg-border" />
                    <span className="text-xs text-muted-foreground">或</span>
                    <div className="flex-1 h-px bg-border" />
                  </div>
                  <div className="flex justify-center">
                    <GoogleOAuthProvider clientId={googleClientId}>
                      <GoogleLogin onSuccess={handleGoogleSuccess} onError={() => setError('Google 登入失敗，請重試')}
                        theme={isDark ? 'filled_black' : 'outline'} shape="rectangular" width="320" />
                    </GoogleOAuthProvider>
                  </div>
                </>
              )}
            </>
          ) : (
            <div className="space-y-5">
              <div className="text-center space-y-1">
                <p className="text-base font-semibold text-foreground">雙重驗證</p>
                <p className="text-sm text-muted-foreground">請開啟 Google Authenticator 或 Authy，輸入 6 位數驗證碼</p>
              </div>
              <input
                ref={totpRef}
                type="text"
                aria-label="6 位數雙重驗證碼"
                autoComplete="one-time-code"
                inputMode="numeric"
                value={totpCode}
                onChange={e => handleTotpChange(e.target.value)}
                placeholder="000000"
                maxLength={6}
                disabled={loading}
                className="w-full text-center text-3xl font-mono tracking-[0.5em] border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-foreground placeholder-gray-300 dark:placeholder-gray-600 rounded-lg px-3 py-4 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
              />
              {loading && <p className="text-center text-sm text-muted-foreground">驗證中…</p>}
              <button onClick={() => { setTempToken(null); setTotpCode(''); setError(null) }}
                className="w-full py-2 text-sm text-muted-foreground hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
                ← 返回重新輸入帳號密碼
              </button>
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">{error}</p>
          )}
        </div>
      </div>
    </div>
  )
}
