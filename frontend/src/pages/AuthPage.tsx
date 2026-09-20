import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { CircleAlert, Eye, EyeOff } from 'lucide-react'
import { IDLE_LOGOUT_FLAG, useAuth } from '../lib/auth'
import { SalesLensMark } from '../components/SalesLensMark'

type Mode = 'signin' | 'signup'
type Notice = { kind: 'error' | 'info'; code: string | null; message: string; title?: string }

export default function AuthPage() {
  const { signIn, signUp } = useAuth()
  const navigate = useNavigate()

  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (sessionStorage.getItem(IDLE_LOGOUT_FLAG)) {
      sessionStorage.removeItem(IDLE_LOGOUT_FLAG)
      setNotice({
        kind: 'info',
        title: 'Signed out',
        code: null,
        message: 'You were signed out after 30 minutes of inactivity.',
      })
    }
  }, [])

  function setModeAndReset(next: Mode) {
    setMode(next)
    setNotice(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return

    if (mode === 'signup' && password.length < 8) {
      setNotice({ kind: 'error', code: null, message: 'Password must be at least 8 characters.' })
      return
    }

    setSubmitting(true)
    setNotice(null)
    try {
      if (mode === 'signin') {
        await signIn(email, password)
        navigate('/dashboard')
      } else {
        const { needsConfirmation } = await signUp(email, password)
        if (needsConfirmation) {
          setNotice({
            kind: 'info',
            code: null,
            message:
              'Account created. Check your email to confirm your address before signing in.',
          })
        } else {
          navigate('/dashboard')
        }
      }
    } catch (error) {
      const err = error as { code?: string; message?: string }
      setNotice({
        kind: 'error',
        code: err.code ?? null,
        message: err.message ?? 'Authentication failed. Please verify your credentials.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  const tabClass = (active: boolean) =>
    'flex-1 px-2 py-1.5 rounded text-center text-label-md transition-all duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary ' +
    (active
      ? 'border border-line bg-card font-semibold text-ink'
      : 'font-medium text-on-surface-variant hover:text-on-surface')

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4 py-12">
      <div className="w-full max-w-md">
        <div className="relative flex flex-col gap-6 rounded-card border border-line bg-card p-8">
          <div className="flex flex-col items-center gap-1 text-center">
            <div className="flex h-8 items-center gap-2">
              <SalesLensMark size={24} />
              <span className="font-display text-lg font-bold tracking-tight text-brand">
                OpportunityCue
              </span>
            </div>
            <p className="text-label-md text-ink-soft">
              Evidence-backed prospecting
            </p>
          </div>

          <div
            aria-label="Authentication mode"
            role="tablist"
            className="flex items-center gap-0.5 rounded-md bg-surface-container-low p-0.5"
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'signin'}
              onClick={() => setModeAndReset('signin')}
              className={tabClass(mode === 'signin')}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'signup'}
              onClick={() => setModeAndReset('signup')}
              className={tabClass(mode === 'signup')}
            >
              Sign up
            </button>
          </div>

          {notice && (
            <div
              role="alert"
              className={
                'flex items-start gap-2 rounded-lg p-3 ' +
                (notice.kind === 'error' ? 'bg-error-container/40' : 'bg-surface-container-low')
              }
            >
              {notice.kind === 'error' && (
                <CircleAlert size={18} className="mt-px shrink-0 text-error" />
              )}
              <div className="min-w-0 flex-1">
                <div className="mb-0.5 flex items-center justify-between gap-2">
                  <span
                    className={
                      'text-label-sm font-medium uppercase ' +
                      (notice.kind === 'error' ? 'text-error' : 'text-on-surface-variant')
                    }
                  >
                    {notice.title ??
                      (notice.kind === 'error' ? 'Authentication error' : 'Confirmation required')}
                  </span>
                  {notice.code && (
                    <span className="font-mono text-[10px] text-error">{notice.code}</span>
                  )}
                </div>
                <p className="text-body-sm leading-snug text-on-surface">
                  {notice.message}
                </p>
              </div>
            </div>
          )}

          <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="email"
                className="text-label-md font-medium text-on-surface-variant"
              >
                Email
              </label>
              <input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="Enter email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="h-10 w-full rounded-control border border-line bg-card px-3 text-body-md text-on-surface outline-none transition-colors placeholder:text-ink-faint focus:border-action focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="password"
                  className="text-label-md font-medium text-on-surface-variant"
                >
                  Password
                </label>
                {mode === 'signup' && (
                  <span className="text-label-sm text-outline">Minimum 8 characters</span>
                )}
              </div>
              <div className="relative flex items-center">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  minLength={mode === 'signup' ? 8 : undefined}
                  autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                  placeholder="Enter password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="h-10 w-full rounded-control border border-line bg-card px-3 pr-10 text-body-md text-on-surface outline-none transition-colors placeholder:text-ink-faint focus:border-action focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
                />
                <button
                  type="button"
                  aria-label="Toggle password visibility"
                  onClick={() => setShowPassword((visible) => !visible)}
                  className="absolute right-0 flex h-10 w-10 items-center justify-center text-outline transition-colors hover:text-on-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="mt-2 flex h-10 w-full items-center justify-center rounded-control bg-action text-headline-sm text-white transition-colors duration-150 hover:bg-action-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span>
                {submitting
                  ? mode === 'signin'
                    ? 'Signing in...'
                    : 'Creating account...'
                  : mode === 'signin'
                    ? 'Sign in to workspace'
                    : 'Create platform account'}
              </span>
            </button>
          </form>

          <div className="pt-1 text-center">
            <button
              type="button"
              onClick={() => setModeAndReset(mode === 'signin' ? 'signup' : 'signin')}
              className="text-body-sm text-on-surface-variant transition-colors hover:text-on-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary"
            >
              {mode === 'signin' ? "Don't have an account? " : 'Already have an account? '}
              <span className="font-semibold text-on-surface underline underline-offset-4">
                {mode === 'signin' ? 'Sign up' : 'Sign in'}
              </span>
            </button>
          </div>

        </div>
      </div>
    </main>
  )
}
