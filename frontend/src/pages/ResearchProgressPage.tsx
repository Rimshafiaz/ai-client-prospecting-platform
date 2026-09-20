import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Check, ExternalLink, Loader2, XCircle } from 'lucide-react'
import { api } from '../lib/api'
import { displayLabel } from '../lib/labels'
import { domainOf, sourceTitle } from '../lib/report'
import type {
  CampaignResearchBatchSummary,
  Company,
  ReportListResponse,
  ResearchRequest,
  ResearchSource,
} from '../lib/types'

const EMPTY_BATCH_REQUEST_IDS: string[] = []
import { Button, Notice } from '../components/ui'

type StageState = 'done' | 'active' | 'pending'

function formatTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString() : ''
}

function StageRow({
  label,
  state,
  timestamp,
}: {
  label: string
  state: StageState
  timestamp: string | null
}) {
  return (
    <li className="flex items-center gap-3 border-b border-line-soft py-3 last:border-b-0">
      {state === 'done' && (
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-ink">
          <Check size={12} className="text-canvas" />
        </span>
      )}
      {state === 'active' && <Loader2 size={18} className="animate-spin text-action" />}
      {state === 'pending' && <span className="h-5 w-5 rounded-full border border-line" />}
      <span
        className={
          'flex-1 font-ui text-sm ' + (state === 'pending' ? 'text-ink-faint' : 'text-ink')
        }
      >
        {label}
      </span>
      {timestamp && <span className="font-mono text-xs text-ink-faint">{formatTime(timestamp)}</span>}
    </li>
  )
}

function BatchStrip({
  batchRequestIds,
  currentRequestId,
}: {
  batchRequestIds: string[]
  currentRequestId: string | null
}) {
  const navigate = useNavigate()
  const [members, setMembers] = useState<
    Record<string, { name: string; status: string; gate: string | null }>
  >({})

  useEffect(() => {
    const others = batchRequestIds.filter((id) => id !== currentRequestId)
    if (others.length === 0) return
    let cancelled = false
    const load = async () => {
      const results = await Promise.all(
        others.map((id) =>
          api<ResearchRequest>(`/research-requests/${id}`).catch(() => null),
        ),
      )
      if (cancelled) return
      const next: Record<string, { name: string; status: string; gate: string | null }> = {}
      results.forEach((data) => {
        if (!data) return
        const target = (data.objective as Record<string, unknown> | null)
          ?.resolved_target as { business_name?: string } | undefined
        next[data.id] = {
          name: target?.business_name ?? data.id.slice(0, 8),
          status: data.status,
          gate: data.evidence_gate_state ?? null,
        }
      })
      setMembers(next)
    }
    void load()
    const timer = window.setInterval(load, 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [batchRequestIds, currentRequestId])

  const others = batchRequestIds.filter((id) => id !== currentRequestId)
  if (others.length === 0) return null

  const statusLabel = (member: { status: string; gate: string | null } | undefined) => {
    if (!member) return 'starting...'
    if (member.status === 'completed')
      return member.gate === 'ready_for_deeper_research'
        ? 'evidence ready, review it'
        : 'finished, needs review'
    if (member.status === 'running') return 'collecting evidence...'
    return 'waiting...'
  }

  return (
    <section className="mt-6 rounded-card border border-line-soft bg-card p-4">
      <p className="label-caps text-ink-faint">Research batch</p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {batchRequestIds.map((id) => {
          if (id === currentRequestId) {
            return (
              <li
                key={id}
                className="rounded-control border border-action px-3 py-1 text-[12px] font-medium text-ink"
              >
                Reviewing now
              </li>
            )
          }
          return (
            <li key={id}>
              <button
                type="button"
                onClick={() => navigate(`/research/${id}`, { state: { batchRequestIds } })}
                className="rounded-control border border-line px-3 py-1 text-[12px] text-ink-soft transition-colors hover:border-action hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
              >
                {members[id]?.name ?? 'Prospect'}: {statusLabel(members[id])}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export default function ResearchProgressPage() {
  const { requestId } = useParams<{ requestId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const batchRequestIds =
    (location.state as { batchRequestIds?: string[] } | null)?.batchRequestIds
    ?? EMPTY_BATCH_REQUEST_IDS
  const [batchSummary, setBatchSummary] = useState<CampaignResearchBatchSummary | null>(null)

  const [request, setRequest] = useState<ResearchRequest | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [company, setCompany] = useState<Company | null>(null)
  const [sources, setSources] = useState<ResearchSource[] | null>(null)
  const [generatePhase, setGeneratePhase] = useState<'idle' | 'starting' | 'polling'>('idle')
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [evidencePhase, setEvidencePhase] = useState<'idle' | 'starting'>('idle')
  const [evidenceError, setEvidenceError] = useState<string | null>(null)

  useEffect(() => {
    if (!requestId) return
    let cancelled = false
    const load = () =>
      api<CampaignResearchBatchSummary>(
        `/campaigns/research-batches/by-request/${requestId}`,
      )
        .then((summary) => {
          if (!cancelled) setBatchSummary(summary)
        })
        .catch(() => {
          if (!cancelled) setBatchSummary(null)
        })
    load()
    const timer = window.setInterval(load, 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [requestId])

  const durableBatchRequestIds = useMemo(
    () => batchSummary?.members.map((member) => member.research_request_id) ?? batchRequestIds,
    [batchSummary, batchRequestIds],
  )
  const loadRequest = useCallback(async () => {
    if (!requestId) return null
    try {
      const data = await api<ResearchRequest>(`/research-requests/${requestId}`)
      setRequest(data)
      setLoadError(null)
      return data
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load the research request.')
      return null
    }
  }, [requestId])

  useEffect(() => {
    void loadRequest()
  }, [loadRequest])

  useEffect(() => {
    if (!request || company) return
    api<Company>(`/companies/${request.company_id}`)
      .then(setCompany)
      .catch(() => setCompany(null))
  }, [request, company])

  useEffect(() => {
    if (request?.status !== 'completed' || sources) return
    api<ResearchSource[]>(`/research-requests/${request.id}/sources`)
      .then(setSources)
      .catch(() => setSources([]))
  }, [request, sources])

  useEffect(() => {
    if (loadError) return
    if (request?.objective?.mode === 'known_prospect' && request.status === 'pending') return
    if (request && (request.status === 'completed' || request.status === 'failed')) return
    const interval = setInterval(() => void loadRequest(), 3000)
    return () => clearInterval(interval)
  }, [request, loadError, loadRequest])

  async function handleGenerate() {
    if (!request || generatePhase !== 'idle') return
    setGenerateError(null)
    setGeneratePhase('starting')
    try {
      await api<unknown[]>(`/research-requests/${request.id}/qualifications`, {
        method: 'POST',
        body: {},
      })
      await api<{ status: string }>(`/research-requests/${request.id}/reports`, {
        method: 'POST',
      })
      setGeneratePhase('polling')
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : 'Could not start report generation.')
      setGeneratePhase('idle')
    }
  }

  async function handleStartEvidenceReview() {
    if (!request || evidencePhase !== 'idle') return
    setEvidencePhase('starting')
    setEvidenceError(null)
    try {
      await api<{ status: string }>(`/research-requests/${request.id}/evidence-gate`, {
        method: 'POST',
      })
      setRequest({ ...request, status: 'running' })
    } catch (e) {
      setEvidenceError(e instanceof Error ? e.message : 'Could not start evidence review.')
      setEvidencePhase('idle')
    }
  }

  useEffect(() => {
    if (generatePhase !== 'polling' || !request) return
    const requestIdLocal = request.id
    let attempts = 0
    const interval = setInterval(async () => {
      attempts += 1
      try {
        const page = await api<ReportListResponse>('/reports', {
          params: { page: 1, page_size: 5 },
        })
        const found = page.items.find(
          (item) => item.research_request_id === requestIdLocal,
        )
        if (found) {
          setGeneratePhase('idle')
          navigate(`/reports/${found.id}`, {
            state: durableBatchRequestIds.length > 0
              ? { batchRequestIds: durableBatchRequestIds }
              : undefined,
          })
          return
        }
      } catch {
        // transient poll failure; keep polling
      }
      if (attempts >= 200) {
        setGeneratePhase('idle')
        setGenerateError(
          'Generation did not finish in time. Check History; the report may appear there.',
        )
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [generatePhase, request, navigate, durableBatchRequestIds])

  async function handleRetry() {
    if (!request) return
    try {
      const fresh = await api<{ id: string }>(
        `/research-requests/${request.id}/retry`,
        { method: 'POST' },
      )
      setRequest(null)
      setSources(null)
      const updatedBatchRequestIds = durableBatchRequestIds.map((id) =>
        id === request.id ? fresh.id : id,
      )
      navigate(`/research/${fresh.id}`, {
        state:
          updatedBatchRequestIds.length > 0
            ? { batchRequestIds: updatedBatchRequestIds }
            : undefined,
      })
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not start a new request.')
    }
  }

  if (loadError) {
    return (
      <main className="workspace-page">
        <Notice kind="error">{loadError}</Notice>
        <p className="mt-4 text-sm">
          <Link to="/dashboard" className="text-action hover:underline">
            Back to dashboard
          </Link>
        </p>
      </main>
    )
  }

  if (!request) {
    return (
      <main className="workspace-page">
        <div className="h-32 animate-pulse rounded-card border border-line-soft bg-card" />
      </main>
    )
  }

  const companyTitle = company?.name ?? 'Research request'
  const failed = request.status === 'failed'
  const completed = request.status === 'completed'
  const running = request.status === 'running'
  const isKnownProspect = request.objective?.mode === 'known_prospect'

  if (isKnownProspect) {
    const goal = typeof request.objective?.goal === 'string' ? request.objective.goal : null
    const offering =
      typeof request.objective?.offering === 'string' ? request.objective.offering : null

    return (
      <main className="workspace-page">
        <p className="label-caps text-ink-faint">Known prospect confirmed</p>
        <h1 className="mt-1 page-title">{companyTitle}</h1>
        <section className="mt-6 rounded-card border border-line-soft bg-card p-5">
          <span className="rounded-control bg-good-wash px-2.5 py-1 font-mono text-[11px] uppercase text-good-ink">
            Identity verified
          </span>
          <h2 className="mt-4 font-display text-xl font-semibold text-ink">
            {request.status === 'pending'
              ? 'Ready for evidence review'
              : request.status === 'running'
                ? 'Reviewing evidence'
                : request.evidence_gate_state === 'ready_for_deeper_research'
                  ? 'Evidence accepted'
                  : 'Evidence needs review'}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-soft">
            {request.status === 'pending'
              ? 'OpportunityCue saved the verified company and research scope. Start a bounded evidence review when you are ready.'
              : request.status === 'running'
                ? 'OpportunityCue is collecting target-scoped public sources and excluding anything it cannot link to this business.'
                : request.evidence_gate_reason}
          </p>
          {(goal || offering) && (
            <dl className="mt-5 grid gap-4 border-t border-line-soft pt-4 sm:grid-cols-2">
              {offering && (
                <div>
                  <dt className="label-caps text-ink-faint">Offering</dt>
                  <dd className="mt-1 text-sm text-ink">{offering}</dd>
                </div>
              )}
              {goal && (
                <div>
                  <dt className="label-caps text-ink-faint">Goal</dt>
                  <dd className="mt-1 text-sm text-ink">{goal}</dd>
                </div>
              )}
            </dl>
          )}
          <div className="mt-5">
            {failed ? (
              <Button onClick={handleRetry}>Try again</Button>
            ) : request.status === 'pending' ? (
              <Button onClick={handleStartEvidenceReview} disabled={evidencePhase !== 'idle'}>
                {evidencePhase === 'starting' ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Starting review...
                  </>
                ) : (
                  'Review evidence'
                )}
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => navigate('/research')}>
                Research another company
              </Button>
            )}
          </div>
          {evidenceError && (
            <div className="mt-3">
              <Notice kind="error">{evidenceError}</Notice>
            </div>
          )}
        </section>
      </main>
    )
  }

  const stages: { label: string; state: StageState; timestamp: string | null }[] = [
    { label: 'Request accepted', state: 'done', timestamp: request.created_at },
    {
      label: 'Resolving company website',
      state: request.started_at ? 'done' : 'active',
      timestamp: request.started_at,
    },
    {
      label: 'Collecting web evidence',
      state: completed || failed ? 'done' : running ? 'active' : 'pending',
      timestamp: null,
    },
    {
      label: 'Evidence ready',
      state: completed ? 'done' : 'pending',
      timestamp: request.finished_at,
    },
  ]

  return (
    <main className="workspace-page">
      <p className="label-caps text-ink-faint">
        Research request <span className="font-mono">{request.id.slice(0, 8)}</span>
      </p>
      <h1 className="mt-1 page-title">{companyTitle}</h1>

      <BatchStrip batchRequestIds={durableBatchRequestIds} currentRequestId={request.id} />

      {batchSummary && (
        <p className="mt-3 text-body-sm text-on-surface-variant">
          {batchSummary.qualified} qualified · {batchSummary.not_a_fit} not a fit ·{' '}
          {batchSummary.needs_review} needs review · {batchSummary.failed} failed ·{' '}
          {batchSummary.pending} pending · {batchSummary.remaining_count} research candidates remaining
        </p>
      )}

      <section className="mt-6 rounded-card border border-line-soft bg-card p-5">
        <h2 className="label-caps text-ink-soft">Investigation progress</h2>
        <ul className="mt-2">
          {stages.map((stage) => (
            <StageRow key={stage.label} {...stage} />
          ))}
          {failed && (
            <li className="flex items-center gap-3 py-3">
              <XCircle size={20} className="text-bad-ink" />
              <span className="flex-1 font-ui text-sm text-bad-ink">Research failed</span>
              <span className="font-mono text-xs text-ink-faint">
                {formatTime(request.finished_at)}
              </span>
            </li>
          )}
        </ul>
        {failed && request.error_message && (
          <div className="mt-2">
            <Notice kind="error">{request.error_message}</Notice>
          </div>
        )}
        {failed && (
          <div className="mt-3">
            <Button onClick={handleRetry}>Try again</Button>
          </div>
        )}
      </section>

      {completed && request.evidence_gate_state !== 'ready_for_deeper_research' && (
        <section className="mt-6 rounded-card border border-line-soft bg-card p-5">
          <h2 className="label-caps text-ink-soft">Evidence review required</h2>
          <p className="mt-2 text-sm leading-relaxed text-ink-soft">
            {request.evidence_gate_reason ?? 'Evidence has not passed the target-match gate.'}
          </p>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-soft">
            This business is not lost. If it has no public web presence, find its
            Facebook or Instagram page yourself and come back to verify it, or
            move on to the next prospect in your batch.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {durableBatchRequestIds.filter((id) => id !== requestId).length > 0 && (
              <Button
                onClick={() =>
                  navigate(
                    `/research/${durableBatchRequestIds.find((id) => id !== requestId)}`,
                    {
                      state: { batchRequestIds: durableBatchRequestIds },
                    },
                  )
                }
              >
                Next prospect in batch
              </Button>
            )}
            <Button variant="secondary" onClick={() => navigate(-1)}>
              Back to prospect queue
            </Button>
            <Link
              to="/campaigns"
              className="text-label-md font-semibold text-action hover:text-ink"
            >
              View campaigns
            </Link>
          </div>
        </section>
      )}

      {completed && request.evidence_gate_state === 'ready_for_deeper_research' && (
        <>
          <section className="mt-6 rounded-card border border-line-soft bg-card p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="label-caps text-ink-soft">
                Evidence collected {sources ? `(${sources.length} sources)` : ''}
              </h2>
              {generatePhase === 'polling' ? (
                <div className="flex items-center gap-2 rounded-control bg-slate-wash p-2.5">
                  <Loader2 size={15} className="animate-spin text-action" />
                  <p className="font-ui text-sm text-ink">
                    Report generation is running. This takes 1 to 5 minutes; you
                    will be moved to the report automatically.
                  </p>
                </div>
              ) : (
                <Button onClick={handleGenerate} disabled={generatePhase !== 'idle'}>
                  {generatePhase === 'starting' ? (
                    <>
                      <Loader2 size={15} className="animate-spin" />
                      Starting...
                    </>
                  ) : (
                    'Generate report'
                  )}
                </Button>
              )}
            </div>
            {generateError && (
              <div className="mt-3">
                <Notice kind="error">{generateError}</Notice>
              </div>
            )}
            {generatePhase === 'polling' && (
              <p className="mt-3 font-narrative text-sm leading-relaxed text-ink-soft">
                OpportunityCue is preparing the report from the accepted evidence. The
                platform never sends outreach without your approval.
              </p>
            )}
            {sources && (
              <ul className="mt-4 divide-y divide-line-soft">
                {sources.map((source) => (
                  <li key={source.id} className="flex items-center gap-3 py-2.5">
                    <span className="label-caps w-24 shrink-0 text-ink-faint">
                      {displayLabel(source.source_type)}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-narrative text-sm text-ink">
                      {sourceTitle(source.title, source.url)}
                    </span>
                    <span className="label-caps text-ink-faint">
                      {displayLabel(source.admission_state)}
                    </span>
                    <a
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-soft hover:text-action"
                    >
                      {domainOf(source.url)}
                      <ExternalLink size={11} />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </main>
  )
}
