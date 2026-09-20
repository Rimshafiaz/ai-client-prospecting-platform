import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, ExternalLink, Loader2, Search } from 'lucide-react'
import { api } from '../lib/api'
import { displayLabel } from '../lib/labels'
import type { Company, KnownProspectResolution } from '../lib/types'
import { Button, Notice, TextField } from '../components/ui'
import {
  OPPORTUNITY_MODEL_LABELS,
  opportunityModelScopeForText,
} from '../lib/opportunityModels'

function isValidWebsite(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

export default function ResearchPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [website, setWebsite] = useState('')
  const [offering, setOffering] = useState('')
  const [goal, setGoal] = useState('')
  const [region, setRegion] = useState('')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [companies, setCompanies] = useState<Company[] | null>(null)
  const [companiesError, setCompaniesError] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [resolution, setResolution] = useState<KnownProspectResolution | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Company[]>('/companies')
      .then(setCompanies)
      .catch((e: unknown) =>
        setCompaniesError(e instanceof Error ? e.message : 'Could not load companies.'),
      )
  }, [])

  function clearResolution() {
    setResolution(null)
    setError(null)
  }

  function payload() {
    const cleanName = name.trim()
    const cleanWebsite = website.trim()
    const cleanOffering = offering.trim()
    const cleanGoal = goal.trim()
    const cleanRegion = region.trim()
    const cleanPhoneNumber = phoneNumber.trim()
    return {
      business_name: cleanName,
      goal: cleanGoal,
      offering: cleanOffering,
      desired_outcome: 'Decide whether this prospect merits evidence review before outreach.',
      ...(cleanRegion ? { location: cleanRegion } : {}),
      ...(cleanWebsite ? { website: cleanWebsite } : {}),
      ...(cleanPhoneNumber ? { phone_number: cleanPhoneNumber } : {}),
    }
  }

  const modelScope = opportunityModelScopeForText(offering, goal)

  function validate() {
    const request = payload()
    if (!request.business_name) return 'Company name is required.'
    if (!request.offering) return 'Say what you are offering so the research can be scoped.'
    if (!request.goal) {
      return 'State the research goal, e.g. decide whether this business is worth pitching.'
    }
    if (website.trim() && !isValidWebsite(website.trim())) {
      return 'Website must be a valid http(s) URL.'
    }
    if (modelScope.error) return modelScope.error
    return null
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (resolving || confirming) return

    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    setResolving(true)
    setError(null)
    try {
      const resolved = await api<KnownProspectResolution>('/known-prospects/resolve', {
        method: 'POST',
        body: payload(),
      })
      setResolution(resolved)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not resolve this business identity.')
    } finally {
      setResolving(false)
    }
  }

  async function handleConfirm() {
    if (!resolution || resolution.identity_state !== 'verified' || confirming) return

    setConfirming(true)
    setError(null)
    try {
      const request = await api<{ id: string }>('/known-prospects/confirm', {
        method: 'POST',
        body: {
          ...payload(),
          model_selection: {
            model_ids: modelScope.modelIds,
            confirmed_by_user: true,
          },
        },
      })
      navigate(`/research/${request.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not confirm this prospect.')
      setConfirming(false)
    }
  }

  function selectCompany(company: Company) {
    setName(company.name)
    setWebsite(company.website ?? '')
    clearResolution()
  }

  const isVerified = resolution?.identity_state === 'verified'

  return (
    <main className="workspace-page">
      <header>
      <h1 className="page-title">Research a company</h1>
      <p className="page-description">
        Define what you offer and what you need to decide. OpportunityCue verifies the
        business identity before it creates an evidence-review request.
      </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="mt-6 rounded-card border border-line-soft bg-card p-5"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Company name"
            hint="Required"
            placeholder="e.g. Aleezay Hair Beauty Care Salon"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
              clearResolution()
            }}
          />
          <TextField
            label="Website"
            hint="Optional"
            placeholder="https://example.com"
            value={website}
            onChange={(event) => {
              setWebsite(event.target.value)
              clearResolution()
            }}
          />
          <TextField
            label="What are you offering?"
            hint="Required"
            placeholder="e.g. Website design and online booking setup"
            value={offering}
            onChange={(event) => {
              setOffering(event.target.value)
              clearResolution()
            }}
          />
          <TextField
            label="Research goal"
            hint="Required"
            placeholder="e.g. Decide whether this business is worth pitching"
            value={goal}
            onChange={(event) => {
              setGoal(event.target.value)
              clearResolution()
            }}
          />
          <TextField
            label="City or region"
            hint="Optional, recommended"
            placeholder="e.g. Lahore"
            value={region}
            onChange={(event) => {
              setRegion(event.target.value)
              clearResolution()
            }}
          />
          <TextField
            label="Business phone"
            hint="Optional"
            placeholder="e.g. +92 300 1234567"
            value={phoneNumber}
            onChange={(event) => {
              setPhoneNumber(event.target.value)
              clearResolution()
            }}
          />
        </div>
        {error && (
          <div className="mt-4" aria-live="polite">
            <Notice kind="error">{error}</Notice>
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <Button type="submit" disabled={resolving || confirming}>
            {resolving ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                Resolving identity...
              </>
            ) : (
              <>
                <Search size={15} />
                Resolve business
              </>
            )}
          </Button>
        </div>
      </form>

      {resolution && (
        <section className="mt-5 rounded-card border border-line-soft bg-card p-5" aria-live="polite">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="label-caps text-ink-faint">Identity check</p>
              <h2 className="mt-1 font-display text-xl font-semibold text-ink">
                {resolution.business_name}
              </h2>
              <p className="mt-1 text-sm text-ink-soft">{resolution.reason}</p>
            </div>
            <span
              className={
                'rounded-control px-2.5 py-1 font-mono text-[11px] uppercase ' +
                (isVerified ? 'bg-good-wash text-good-ink' : 'bg-warn-wash text-warn-ink')
              }
            >
              {isVerified ? 'Verified' : 'Needs review'}
            </span>
          </div>
          {resolution.website && (
            <a
              href={resolution.website}
              target="_blank"
              rel="noreferrer"
              className="mt-4 inline-flex items-center gap-1 font-mono text-xs text-action hover:underline"
            >
              {resolution.website.replace(/^https?:\/\//, '')}
              <ExternalLink size={12} />
            </a>
          )}
          {resolution.source?.source_url && (
            <p className="mt-3 font-mono text-[11px] text-ink-faint">
              Source: {displayLabel(resolution.source.provider)}
            </p>
          )}
          {isVerified ? (
            <div className="mt-5 border-t border-line-soft pt-4">
              <div>
                <p className="label-caps text-ink-faint">Research scope</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {modelScope.modelIds.map((modelId) => (
                    <span
                      key={modelId}
                      className="rounded-control bg-secondary-container px-2 py-1 text-label-sm text-on-surface"
                    >
                      {OPPORTUNITY_MODEL_LABELS[modelId]}
                    </span>
                  ))}
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <p className="max-w-xl text-sm text-ink-soft">
                  Confirming creates a pending evidence-review request with this scope. It
                  does not start a report or send outreach.
                </p>
                <Button onClick={handleConfirm} disabled={confirming || !!modelScope.error}>
                {confirming ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    Confirming...
                  </>
                ) : (
                  <>
                    <Check size={15} />
                    Confirm prospect
                  </>
                )}
                </Button>
              </div>
            </div>
          ) : (
            <div className="mt-4">
              <Notice kind="info">
                Adjust the company details or website and resolve again. OpportunityCue will
                not create research for an ambiguous identity.
              </Notice>
            </div>
          )}
        </section>
      )}

      <section className="mt-10">
        <div className="flex items-baseline justify-between">
          <h2 className="font-display text-lg font-semibold text-ink">Use an existing company</h2>
          <p className="text-xs text-ink-faint">This fills the form; it does not start research.</p>
        </div>

        {companiesError && (
          <div className="mt-3">
            <Notice kind="error">{companiesError}</Notice>
          </div>
        )}

        {companies === null && !companiesError && (
          <div className="mt-3 h-16 animate-pulse rounded-card border border-line-soft bg-card" />
        )}

        {companies && companies.length === 0 && (
          <div className="mt-3 rounded-card border border-line-soft bg-card p-6 text-center">
            <p className="font-narrative text-sm text-ink-soft">
              You have no companies yet. Add one with the form above.
            </p>
          </div>
        )}

        {companies && companies.length > 0 && (
          <div className="mt-3 divide-y divide-line-soft rounded-card border border-line-soft bg-card">
            {companies.map((company) => (
              <div
                key={company.id}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
              >
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-control border border-line bg-canvas font-display text-sm font-semibold text-ink">
                    {company.name.charAt(0).toUpperCase()}
                  </span>
                  <div>
                    <p className="font-ui text-sm font-semibold text-ink">{company.name}</p>
                    {company.website && (
                      <a
                        href={company.website}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 font-mono text-[11px] text-ink-soft hover:text-action"
                      >
                        {company.website.replace(/^https?:\/\//, '')}
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                </div>
                <Button variant="secondary" onClick={() => selectCompany(company)}>
                  Use details
                </Button>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  )
}
