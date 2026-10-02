import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Lock, User, LogIn, Eye, EyeOff, AlertCircle } from 'lucide-react'
import { api } from '../services/api'
import type { UserProfile } from '../types/api'
import octaveLogo from '../assets/octave-logo.png'

function applySavedTheme() {
  try {
    document.documentElement.setAttribute('data-theme', localStorage.getItem('app_theme') === 'light' ? 'light' : 'dark')
  } catch {
    document.documentElement.setAttribute('data-theme', 'dark')
  }
}

export function LoginPage({ onSignedIn }: { onSignedIn: (profile: UserProfile) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(applySavedTheme, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      onSignedIn(await api.login(username.trim(), password))
    } catch (err) {
      const message = err instanceof Error ? err.message : ''
      setError(message.startsWith('429') ? 'Too many failed attempts. Please wait a few minutes and try again.'
        : message.startsWith('401') ? 'Invalid username or password.'
        : 'Sign-in is unavailable right now. Please try again.')
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="loginScreen">
      <form className="loginCard" onSubmit={submit} data-testid="login-form" autoComplete="on">
        <div className="loginBrand">
          <div className="logo brandLogo"><img src={octaveLogo} alt="Octave" className="logoImg" /></div>
          <div>
            <h1>ADO Pipeline Insight</h1>
            <p>Sign in to continue</p>
          </div>
        </div>

        <label className="loginField">
          <span>Username</span>
          <div className="loginInput">
            <User size={15} />
            <input
              data-testid="login-username"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={e => setUsername(e.target.value)}
              maxLength={128}
              required
            />
          </div>
        </label>

        <label className="loginField">
          <span>Password</span>
          <div className="loginInput">
            <Lock size={15} />
            <input
              data-testid="login-password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              maxLength={256}
              required
            />
            <button type="button" className="loginEye" onClick={() => setShowPassword(v => !v)} aria-label={showPassword ? 'Hide password' : 'Show password'}>
              {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
        </label>

        {error && <div className="loginError" role="alert" data-testid="login-error"><AlertCircle size={14} />{error}</div>}

        <button type="submit" className="loginSubmit" disabled={busy || !username.trim() || !password} data-testid="login-submit">
          <LogIn size={15} />{busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}

/** Shows the sign-in screen until the server confirms a session; any 401 from the API sends the user back here. */
export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const { data: profile, isLoading } = useQuery<UserProfile>({
    queryKey: ['user-profile'],
    queryFn: api.me,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })

  useEffect(() => {
    const onExpired = () => {
      queryClient.setQueryData<UserProfile>(['user-profile'], { authenticated: false, loginRequired: true, userId: null, email: null, name: null, provider: null })
    }
    window.addEventListener('auth-expired', onExpired)
    return () => window.removeEventListener('auth-expired', onExpired)
  }, [queryClient])

  if (isLoading) return <div className="loginScreen" aria-busy="true" />
  if (!profile || (!profile.authenticated && profile.loginRequired !== false)) {
    return (
      <LoginPage
        onSignedIn={p => {
          queryClient.setQueryData(['user-profile'], p)
          queryClient.invalidateQueries({
            predicate: query => query.queryKey[0] !== 'user-profile',
          })
        }}
      />
    )
  }
  return <>{children}</>
}
