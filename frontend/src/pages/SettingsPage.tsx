import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button, Notice } from '../components/ui'
import { api } from '../lib/api'
import type { GmailAuthorization, GmailConnection } from '../lib/types'


export default function SettingsPage() {
  const [searchParams] = useSearchParams()
  const [connection, setConnection] = useState<GmailConnection | null>(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    api<GmailConnection>('/integrations/gmail')
      .then((data) => {
        if (active) setConnection(data)
      })
      .catch((requestError: unknown) => {
        if (active) setError(requestError instanceof Error ? requestError.message : 'Could not load integrations.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  async function connect() {
    setWorking(true)
    setError(null)
    try {
      const result = await api<GmailAuthorization>('/integrations/gmail/connect', { method: 'POST' })
      window.location.assign(result.authorization_url)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not start Gmail connection.')
      setWorking(false)
    }
  }

  async function disconnect() {
    setWorking(true)
    setError(null)
    try {
      await api('/integrations/gmail', { method: 'DELETE' })
      setConnection((current) => current ? { ...current, status: 'disconnected' } : current)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not disconnect Gmail.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <main className="workspace-page">
      <header className="border-b border-line pb-6">
        <h1 className="page-title">Settings</h1>
        <p className="page-description">Manage accounts used for outreach.</p>
      </header>

      <div className="mt-4 space-y-2">
        {searchParams.get('gmail') === 'connected' && <Notice kind="info">Gmail connected successfully.</Notice>}
        {searchParams.get('gmail') === 'error' && <Notice kind="error">Gmail connection was not completed. Please try again.</Notice>}
        {error && <Notice kind="error">{error}</Notice>}
      </div>

      {loading && <div className="mt-4 h-28 animate-pulse border-y border-line bg-card" />}

      {!loading && (
      <section className="mt-4 grid gap-4 border-b border-line py-5 sm:grid-cols-[10rem_minmax(0,1fr)]">
          <h2 className="text-body-md font-semibold text-on-surface">Email</h2>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-body-md font-semibold text-on-surface">Gmail</h3>
                <p className="mt-1 text-body-sm text-on-surface-variant">Send drafts after you approve them.</p>
              </div>
              {connection?.status === 'connected' ? (
                <div className="flex flex-wrap gap-2">
                  {!connection.reply_tracking_enabled && <Button type="button" disabled={working} onClick={() => void connect()}>Reconnect for reply tracking</Button>}
                  <Button type="button" variant="secondary" disabled={working} onClick={() => void disconnect()}>Disconnect</Button>
                </div>
              ) : (
                <Button type="button" disabled={working || connection?.configured === false} onClick={() => void connect()}>Connect Gmail</Button>
              )}
            </div>
            {connection?.status === 'connected' && <p className="mt-3 text-body-sm text-on-surface">Connected as {connection.email}</p>}
            {connection?.status === 'connected' && !connection.reply_tracking_enabled && <p className="mt-3 text-body-sm text-on-surface-variant">Reconnect once to grant Gmail metadata access for checking replies to OpportunityCue-created threads.</p>}
            {connection?.reply_tracking_enabled && <p className="mt-3 text-body-sm text-on-surface-variant">Reply tracking is enabled for Gmail threads created by OpportunityCue.</p>}
            {connection?.configured === false && <p className="mt-3 text-body-sm text-error">Gmail OAuth has not been configured on this OpportunityCue server.</p>}
            <p className="mt-3 text-label-sm text-on-surface-variant">OpportunityCue never sends a draft without your approval.</p>
          </div>
      </section>
      )}
    </main>
  )
}
