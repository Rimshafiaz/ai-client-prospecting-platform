import { useEffect, useState } from 'react'
import { CircleAlert, Loader2 } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { displayLabel } from '../lib/labels'
import type {
  CampaignProspect,
  CampaignResponse,
  OutreachAttempt,
  OutreachDraftOption,
} from '../lib/types'

interface CampaignProspects {
  campaign: CampaignResponse
  prospects: CampaignProspect[]
}

export default function ProspectsPage() {
  const [searchParams] = useSearchParams()
  const [groups, setGroups] = useState<CampaignProspects[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    async function load() {
      try {
        const campaignId = searchParams.get('campaign') ?? undefined
        const [campaigns, prospects] = await Promise.all([
          api<CampaignResponse[]>('/campaigns'),
          api<CampaignProspect[]>('/campaigns/prospects/bulk', {
            params: { campaign_id: campaignId },
          }),
        ])
        const loaded = campaigns.map((campaign) => ({
          campaign,
          prospects: prospects.filter((prospect) => prospect.campaign_id === campaign.id),
        }))
        if (active) setGroups(loaded.filter((group) => group.prospects.length > 0))
      } catch (requestError) {
        if (active) setError(requestError instanceof Error ? requestError.message : 'Could not load prospects.')
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()
    return () => {
      active = false
    }
  }, [searchParams])

  const campaignFilter = searchParams.get('campaign')
  const visibleGroups = campaignFilter
    ? groups.filter(({ campaign }) => campaign.id === campaignFilter)
    : groups

  return (
    <main className="workspace-page">
      <div className="mb-8 border-b border-line pb-6">
        <div>
          <h1 className="page-title">Prospects</h1>
          <p className="page-description">Saved businesses moving through research and outreach.</p>
        </div>
      </div>

      {loading && <div className="flex items-center gap-2 text-body-sm text-on-surface-variant"><Loader2 size={16} className="animate-spin" />Loading prospects...</div>}
      {error && <div className="flex items-start gap-2 rounded-lg bg-error-container/40 p-3 text-body-sm text-on-surface"><CircleAlert size={16} className="mt-0.5 text-error" />{error}</div>}
      {!loading && !error && visibleGroups.length === 0 && (
        <section className="py-12">
          <p className="text-headline-md font-semibold text-on-surface">{campaignFilter ? 'No prospects in this campaign' : 'No saved prospects'}</p>
          <p className="mt-2 text-body-md text-on-surface-variant">{campaignFilter ? 'This campaign does not have saved prospects yet.' : 'Save a candidate from a campaign to keep it here.'}</p>
          {campaignFilter && <Link to="/prospects" className="mt-4 inline-flex text-label-md font-semibold text-action hover:text-ink">View all prospects</Link>}
        </section>
      )}
      <div className="space-y-6">
        {visibleGroups.map(({ campaign, prospects }) => (
          <section key={campaign.id} className="border-b border-line py-6 first:pt-0">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-headline-md font-semibold text-on-surface">{campaign.title}</h2>
              <span className="text-label-md text-on-surface-variant">{prospects.length} saved</span>
            </div>
            <div className="divide-y divide-line-soft">
              {prospects.map((prospect) => (
                <article key={prospect.id} className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <h3 className="font-medium text-on-surface">{String(prospect.candidate_snapshot.company_name ?? 'Unnamed business')}</h3>
                    <p className="mt-1 text-body-sm text-on-surface-variant">{String(prospect.candidate_snapshot.formatted_address ?? 'Location not listed')}</p>
                  </div>
                  <div className="flex items-center gap-3 text-label-md">
                    <span className="rounded-full bg-secondary-container px-2.5 py-1 text-on-secondary-container">{displayLabel(prospect.workflow_state)}</span>
                    <span className="text-on-surface-variant">Next: {displayLabel(prospect.next_action)}</span>
                    <Link to={`/campaigns/${campaign.id}/prospects/${prospect.id}`} className="font-semibold text-secondary hover:text-on-surface">Open</Link>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </main>
  )
}

export function ProspectOutreach({ campaignId, prospect, initialAttempts, initialOptions }: { campaignId: string; prospect: CampaignProspect; initialAttempts?: OutreachAttempt[]; initialOptions?: OutreachDraftOption[] }) {
  const [attempts, setAttempts] = useState<OutreachAttempt[]>(initialAttempts ?? [])
  const [options, setOptions] = useState<OutreachDraftOption[]>(initialOptions ?? [])
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function createDraft(option: OutreachDraftOption) {
    setWorking(true)
    setError(null)
    try {
      const attempt = await api<OutreachAttempt>(
        `/campaigns/${campaignId}/prospects/${prospect.id}/outreach-attempts`,
        {
          method: 'POST',
          body: {
            research_report_id: option.research_report_id,
            channel: option.channel,
            recipient: option.recipient,
          },
        },
      )
      setAttempts((current) => [attempt, ...current])
      setOptions((current) => current.filter((item) => item !== option))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not create outreach draft.')
    } finally {
      setWorking(false)
    }
  }

  if (attempts.length === 0 && options.length === 0 && !error) return null

  return (
    <div className="space-y-3">
      <p className="text-label-sm font-semibold text-ink">Outreach</p>
      {error && <p className="text-body-sm text-error">{error}</p>}
      {options.map((option) => (
        <button key={`${option.research_report_id}:${option.channel}:${option.recipient}`} type="button" disabled={working} onClick={() => createDraft(option)} className="rounded-control border border-secondary px-3 py-1.5 text-label-md font-medium text-secondary hover:bg-secondary-container disabled:opacity-60">
          Create {displayLabel(option.channel)} draft for {option.recipient}
        </button>
      ))}
      {attempts.map((attempt) => (
        <OutreachAttemptCard
          key={attempt.id}
          attempt={attempt}
          working={working}
          setWorking={setWorking}
          setError={setError}
          onChanged={(updated) => setAttempts((current) => current.map((item) => item.id === updated.id ? updated : item))}
        />
      ))}
    </div>
  )
}

function OutreachAttemptCard({
  attempt,
  working,
  setWorking,
  setError,
  onChanged,
}: {
  attempt: OutreachAttempt
  working: boolean
  setWorking: (working: boolean) => void
  setError: (error: string | null) => void
  onChanged: (attempt: OutreachAttempt) => void
}) {
  const [subject, setSubject] = useState(attempt.subject ?? '')
  const [body, setBody] = useState(attempt.body)
  const [replyCheckMessage, setReplyCheckMessage] = useState<string | null>(null)
  const editable = attempt.status === 'draft' || attempt.status === 'approved' || attempt.status === 'failed'
  const changed = subject !== (attempt.subject ?? '') || body !== attempt.body

  async function saveDraft(): Promise<OutreachAttempt> {
    return api<OutreachAttempt>(`/outreach-attempts/${attempt.id}/draft`, {
      method: 'PATCH',
      body: { subject: attempt.channel === 'email' ? subject : null, body },
    })
  }

  async function run(action: 'save' | 'approve' | 'sent' | 'send-email' | 'check-reply') {
    setWorking(true)
    setError(null)
    setReplyCheckMessage(null)
    try {
      let updated = attempt
      if (action === 'save' || (action === 'approve' && changed)) updated = await saveDraft()
      if (action === 'approve') {
        updated = await api<OutreachAttempt>(`/outreach-attempts/${attempt.id}/approve`, { method: 'POST' })
      }
      if (action === 'sent') {
        updated = await api<OutreachAttempt>(`/outreach-attempts/${attempt.id}/manual-send`, { method: 'POST' })
      }
      if (action === 'send-email') {
        updated = await api<OutreachAttempt>(`/outreach-attempts/${attempt.id}/send-email`, { method: 'POST' })
      }
      if (action === 'check-reply') {
        updated = await api<OutreachAttempt>(`/outreach-attempts/${attempt.id}/check-reply`, { method: 'POST' })
        setReplyCheckMessage(updated.status === 'replied' ? 'Reply detected.' : 'No reply detected yet.')
      }
      onChanged(updated)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not update outreach.')
    } finally {
      setWorking(false)
    }
  }

  async function recordOutcome(outcome: 'interested' | 'not_interested' | 'no_response', replied: boolean) {
    setWorking(true)
    setError(null)
    try {
      const updated = await api<OutreachAttempt>(`/outreach-attempts/${attempt.id}/manual-outcome`, {
        method: 'POST',
        body: { outcome, replied },
      })
      onChanged(updated)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not record outreach outcome.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="border-t border-line pt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-label-md font-medium text-on-surface">{displayLabel(attempt.channel)} / {attempt.recipient}</p>
        <span className="rounded-full bg-surface-container-high px-2 py-0.5 text-label-sm text-on-surface-variant">{displayLabel(attempt.status)}</span>
      </div>
      {attempt.channel === 'email' && (
        <input aria-label="Email subject" disabled={!editable || working} value={subject} onChange={(event) => setSubject(event.target.value)} className="mt-3 w-full rounded-control border border-line-soft bg-surface-container-lowest px-3 py-2 text-body-sm text-on-surface" />
      )}
      <textarea aria-label={`${displayLabel(attempt.channel)} message`} disabled={!editable || working} value={body} onChange={(event) => setBody(event.target.value)} rows={6} className="mt-2 w-full rounded-control border border-line-soft bg-surface-container-lowest px-3 py-2 text-body-sm text-on-surface" />
      {editable && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" disabled={working || !changed} onClick={() => void run('save')} className="rounded-control border border-secondary px-3 py-1.5 text-label-md font-medium text-secondary disabled:opacity-60">Save changes</button>
          {(attempt.status === 'draft' || changed) && <button type="button" disabled={working} onClick={() => void run('approve')} className="rounded-control bg-primary px-3 py-1.5 text-label-md font-medium text-on-primary disabled:opacity-60">{attempt.status === 'approved' ? 'Approve changes' : 'Approve draft'}</button>}
        </div>
      )}
      {attempt.edited_by_user && <p className="mt-2 text-label-sm text-on-surface-variant">Edited by you.</p>}
      {attempt.status === 'approved' && attempt.channel === 'email' && !changed && (
        <button type="button" disabled={working} onClick={() => void run('send-email')} className="mt-3 rounded-control bg-primary px-3 py-1.5 text-label-md font-medium text-on-primary disabled:opacity-60">Send with Gmail</button>
      )}
      {attempt.status === 'approved' && attempt.send_method === 'manual' && !changed && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" disabled={working} onClick={() => void navigator.clipboard.writeText(body)} className="rounded-control border border-secondary px-3 py-1.5 text-label-md font-medium text-secondary disabled:opacity-60">Copy message</button>
          <a href={contactHref(attempt.channel, attempt.recipient)} target={attempt.channel === 'phone' ? undefined : '_blank'} rel="noreferrer" className="rounded-control border border-secondary px-3 py-1.5 text-label-md font-medium text-secondary">Open {displayLabel(attempt.channel)}</a>
          <button type="button" disabled={working} onClick={() => void run('sent')} className="rounded-control bg-primary px-3 py-1.5 text-label-md font-medium text-on-primary disabled:opacity-60">Mark sent</button>
        </div>
      )}
      {attempt.send_method === 'manual' && (attempt.status === 'sent' || attempt.status === 'replied') && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" disabled={working} onClick={() => void recordOutcome('interested', true)} className="rounded-control border border-secondary px-3 py-1.5 text-label-md text-secondary disabled:opacity-60">Replied: interested</button>
          <button type="button" disabled={working} onClick={() => void recordOutcome('not_interested', true)} className="rounded-control border border-secondary px-3 py-1.5 text-label-md text-secondary disabled:opacity-60">Replied: not interested</button>
          {attempt.status === 'sent' && <button type="button" disabled={working} onClick={() => void recordOutcome('no_response', false)} className="rounded-control border border-line-soft px-3 py-1.5 text-label-md text-on-surface-variant disabled:opacity-60">Close: no response</button>}
        </div>
      )}
      {attempt.channel === 'email' && attempt.status === 'sent' && <button type="button" disabled={working} onClick={() => void run('check-reply')} className="mt-3 rounded-control border border-secondary px-3 py-1.5 text-label-md font-medium text-secondary disabled:opacity-60">Check for reply</button>}
      {attempt.channel === 'email' && attempt.status === 'replied' && <p className="mt-3 text-body-sm text-on-surface">A reply was detected in the OpportunityCue Gmail thread.</p>}
      {replyCheckMessage && <p className="mt-2 text-label-sm text-on-surface-variant">{replyCheckMessage}</p>}
      {attempt.outcome && <p className="mt-2 text-label-sm text-on-surface-variant">Outcome: {displayLabel(attempt.outcome)}</p>}
      {attempt.failure_reason && <p className="mt-2 text-label-sm text-error">{attempt.failure_reason}</p>}
    </div>
  )
}

function contactHref(channel: OutreachAttempt['channel'], recipient: string): string {
  if (channel === 'phone') return `tel:${recipient}`
  if (channel === 'whatsapp' && !recipient.startsWith('http')) {
    return `https://wa.me/${recipient.replace(/\D/g, '')}`
  }
  return recipient
}
