import { type Dispatch, type SetStateAction, useEffect, useMemo, useState } from 'react'
import './App.css'
import jobHunterLogo from './assets/PTxagentic_job_hunter_logo.png'
import {
  captureLinkedinLead,
  createDraft,
  discoverGreenhouse,
  discoverLever,
  getDashboard,
  runResearch,
  runWorker,
  updateProfile,
  uploadCv,
  uploadLinkedinFile,
  uploadLinkedinText,
} from './api'
import type {
  ApplicationDraftResponse,
  CandidateProfilePayload,
  DashboardResponse,
  JobLeadResponse,
  ScreeningAnswerPayload,
  WorkerFieldState,
  WorkerRunResponse,
} from './types'

type WorkplaceFilterValue = 'all' | 'remote' | 'hybrid' | 'on-site'
type DraftEditorState = {
  cover_note: string
  screening_answers: ScreeningAnswerPayload[]
}

const emptyProfile: CandidateProfilePayload = {
  full_name: '',
  headline: '',
  email: '',
  phone: '',
  location: '',
  summary: '',
  skills: [],
  achievements: [],
  experiences: [],
  education: [],
  links: {},
}
const fitScoreOptions = [0, 40, 50, 60, 70, 80]

function App() {
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [statusMessage, setStatusMessage] = useState('Loading dashboard...')
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [cvFile, setCvFile] = useState<File | null>(null)
  const [linkedinText, setLinkedinText] = useState('')
  const [linkedinFile, setLinkedinFile] = useState<File | null>(null)
  const [greenhouseBoards, setGreenhouseBoards] = useState('openai\nanthropic')
  const [leverBoards, setLeverBoards] = useState('netflix')
  const [manualLead, setManualLead] = useState({
    company: '',
    title: '',
    url: '',
    location: '',
    description: '',
    notes: '',
  })
  const [profileEditor, setProfileEditor] = useState<CandidateProfilePayload>(emptyProfile)
  const [lastWorkerRun, setLastWorkerRun] = useState<WorkerRunResponse | null>(null)
  const [draftEditors, setDraftEditors] = useState<Record<number, DraftEditorState>>({})
  const [reviewOverrides, setReviewOverrides] = useState<Record<number, Record<string, string>>>({})
  const [shortlistFilters, setShortlistFilters] = useState<{
    minScore: number
    location: string
    workplace: WorkplaceFilterValue
  }>({
    minScore: 0,
    location: '',
    workplace: 'all',
  })

  useEffect(() => {
    void refreshDashboard()
  }, [])

  useEffect(() => {
    if (dashboard?.profile?.merged_profile) {
      setProfileEditor(dashboard.profile.merged_profile)
    }
  }, [dashboard?.profile])

  useEffect(() => {
    if (!dashboard?.applications) {
      return
    }
    setDraftEditors((current) => {
      const next = { ...current }
      for (const application of dashboard.applications) {
        if (!next[application.id]) {
          next[application.id] = createDraftEditorState(application)
        }
      }
      return next
    })
  }, [dashboard?.applications])

  useEffect(() => {
    const latestRun = dashboard?.worker_runs?.[0] ?? null
    if (latestRun && latestRun.id !== lastWorkerRun?.id) {
      setLastWorkerRun(latestRun)
    }
  }, [dashboard?.worker_runs, lastWorkerRun?.id])

  useEffect(() => {
    const applicationDraftId = lastWorkerRun?.application_draft_id
    if (!applicationDraftId) {
      return
    }
    setReviewOverrides((current) => {
      const existing = { ...(current[applicationDraftId] ?? {}) }
      for (const field of lastWorkerRun.review_items) {
        if (!(field.field_id in existing)) {
          existing[field.field_id] = field.answer_value ?? ''
        }
      }
      return { ...current, [applicationDraftId]: existing }
    })
  }, [lastWorkerRun?.application_draft_id, lastWorkerRun?.id, lastWorkerRun?.review_items])

  const rankedJobs = useMemo(() => {
    return [...(dashboard?.jobs ?? [])].sort((left, right) => (right.score ?? 0) - (left.score ?? 0))
  }, [dashboard])

  const jobsById = useMemo(() => {
    return new Map((dashboard?.jobs ?? []).map((job) => [job.id, job]))
  }, [dashboard?.jobs])

  const latestRunByApplicationId = useMemo(() => {
    const next = new Map<number, WorkerRunResponse>()
    for (const run of dashboard?.worker_runs ?? []) {
      if (run.application_draft_id && !next.has(run.application_draft_id)) {
        next.set(run.application_draft_id, run)
      }
    }
    return next
  }, [dashboard?.worker_runs])

  const shortlist = useMemo(() => {
    const normalizedLocationFilter = shortlistFilters.location.trim().toLowerCase()

    return rankedJobs.filter((job) => {
      if ((job.score ?? 0) < shortlistFilters.minScore) {
        return false
      }
      if (
        normalizedLocationFilter &&
        !(job.location ?? '').toLowerCase().includes(normalizedLocationFilter)
      ) {
        return false
      }
      if (shortlistFilters.workplace !== 'all') {
        return getWorkplaceType(job) === shortlistFilters.workplace
      }
      return true
    })
  }, [rankedJobs, shortlistFilters])

  const hasShortlistFilters =
    shortlistFilters.minScore > 0 ||
    shortlistFilters.location.trim().length > 0 ||
    shortlistFilters.workplace !== 'all'

  async function refreshDashboard(nextMessage = 'Dashboard is up to date.') {
    try {
      const nextDashboard = await getDashboard()
      setDashboard(nextDashboard)
      setStatusMessage(nextMessage)
    } catch (error) {
      setStatusMessage(getErrorMessage(error))
    }
  }

  async function runAction(key: string, action: () => Promise<string | void>) {
    try {
      setBusyKey(key)
      const nextMessage = await action()
      await refreshDashboard(nextMessage ?? 'Dashboard is up to date.')
    } catch (error) {
      setStatusMessage(getErrorMessage(error))
    } finally {
      setBusyKey(null)
    }
  }

  async function handleCvUpload() {
    if (!cvFile) {
      setStatusMessage('Choose a CV file before uploading.')
      return
    }
    await runAction('cv-upload', async () => {
      await uploadCv(cvFile)
      setCvFile(null)
      return `Parsed CV: ${cvFile.name}`
    })
  }

  async function handleLinkedinImport() {
    if (!linkedinText.trim() && !linkedinFile) {
      setStatusMessage('Paste LinkedIn text or attach an exported file first.')
      return
    }
    await runAction('linkedin-import', async () => {
      if (linkedinFile) {
        await uploadLinkedinFile(linkedinFile)
        setLinkedinFile(null)
      } else {
        await uploadLinkedinText(linkedinText)
        setLinkedinText('')
      }
      return 'LinkedIn profile enrichment merged into the candidate profile.'
    })
  }

  async function handleProfileSave() {
    await runAction('profile-save', async () => {
      await updateProfile({
        ...profileEditor,
        skills: splitLines(profileEditor.skills.join('\n')),
        achievements: splitLines(profileEditor.achievements.join('\n')),
      })
      return 'Manual profile edits saved.'
    })
  }

  async function handleDiscovery(source: 'greenhouse' | 'lever') {
    await runAction(`discover-${source}`, async () => {
      const identifiers =
        source === 'greenhouse' ? splitLines(greenhouseBoards) : splitLines(leverBoards)
      if (identifiers.length === 0) {
        throw new Error(`Add at least one ${source} identifier.`)
      }
      const jobs =
        source === 'greenhouse'
          ? await discoverGreenhouse(identifiers)
          : await discoverLever(identifiers)
      return `Discovered ${jobs.length} ${source} ${jobs.length === 1 ? 'role' : 'roles'} from ${identifiers.length} ${identifiers.length === 1 ? 'identifier' : 'identifiers'}.`
    })
  }

  async function handleLinkedinLeadCapture() {
    if (!manualLead.company || !manualLead.title) {
      setStatusMessage('LinkedIn lead capture requires a company and job title.')
      return
    }
    await runAction('linkedin-lead', async () => {
      await captureLinkedinLead({
        ...manualLead,
        url: manualLead.url || undefined,
        location: manualLead.location || undefined,
        description: manualLead.description || undefined,
        notes: manualLead.notes || undefined,
      })
      setManualLead({
        company: '',
        title: '',
        url: '',
        location: '',
        description: '',
        notes: '',
      })
      return 'LinkedIn lead added to the queue.'
    })
  }

  async function handleResearch(jobId: number) {
    await runAction(`research-${jobId}`, async () => {
      await runResearch(jobId)
      return `Ran company research for job ${jobId}.`
    })
  }

  async function handleDraft(jobId: number) {
    await runAction(`draft-${jobId}`, async () => {
      await createDraft(jobId)
      return `Created an application draft for job ${jobId}.`
    })
  }

  async function handleWorker(
    applicationId: number,
    options: { dryRun: boolean; confirmSubmit: boolean },
  ) {
    const editor = draftEditors[applicationId] ?? createDraftEditorStateFromId(applicationId, dashboard)
    if (!editor) {
      setStatusMessage(`Draft ${applicationId} is no longer available.`)
      return
    }

    const busyLabel = options.confirmSubmit ? `submit-${applicationId}` : `preview-${applicationId}`
    await runAction(busyLabel, async () => {
      const result = await runWorker(applicationId, {
        dry_run: options.dryRun,
        confirm_submit: options.confirmSubmit,
        cover_note: editor.cover_note,
        screening_answers: editor.screening_answers,
        answer_overrides: buildAnswerOverrides(applicationId, reviewOverrides),
      })
      setLastWorkerRun(result)
      seedReviewOverrides(result, setReviewOverrides)
      return buildWorkerStatusMessage(result)
    })
  }

  function updateProfileLink(linkType: 'linkedin' | 'github', value: string) {
    setProfileEditor((current) => ({
      ...current,
      links: {
        ...current.links,
        [linkType]: value,
      },
    }))
  }

  function updateDraftCoverNote(applicationId: number, value: string) {
    setDraftEditors((current) => {
      const base = current[applicationId] ?? createDraftEditorStateFromId(applicationId, dashboard)
      if (!base) {
        return current
      }
      return {
        ...current,
        [applicationId]: {
          ...base,
          cover_note: value,
        },
      }
    })
  }

  function updateScreeningAnswer(applicationId: number, index: number, value: string) {
    setDraftEditors((current) => {
      const base =
        current[applicationId] ?? createDraftEditorStateFromId(applicationId, dashboard)
      if (!base) {
        return current
      }
      const screeningAnswers = base.screening_answers.map((item, itemIndex) =>
        itemIndex === index ? { ...item, answer: value } : item,
      )
      return {
        ...current,
        [applicationId]: {
          ...base,
          screening_answers: screeningAnswers,
        },
      }
    })
  }

  function updateReviewOverride(applicationId: number, fieldId: string, value: string) {
    setReviewOverrides((current) => ({
      ...current,
      [applicationId]: {
        ...(current[applicationId] ?? {}),
        [fieldId]: value,
      },
    }))
  }

  const currentRunApplicationId = lastWorkerRun?.application_draft_id ?? null
  const reviewValueLookup = currentRunApplicationId ? reviewOverrides[currentRunApplicationId] ?? {} : {}
  const autofillReadyFields = (lastWorkerRun?.fields ?? []).filter(
    (field) => field.answer_value && !field.requires_review,
  )

  return (
    <main className="app-shell">
      <section className="hero">
        <div className="panel hero-panel">
          <div className="brand-lockup">
            <img
              src={jobHunterLogo}
              alt="PT x Agentic Job Hunter logo"
              className="brand-logo"
            />
            <div className="brand-meta">
              <p className="eyebrow">PT x AGENTIC</p>
              <p className="brand-name">Job Hunter</p>
            </div>
          </div>
          <h1>Serious job search automation with a final approval gate.</h1>
          <p className="hero-copy">
            Upload your CV, optionally merge LinkedIn data, discover ATS roles, generate tailored
            drafts, preview semantic autofill, review hard questions, and only submit when the
            application looks complete.
          </p>
        </div>
        <aside className="status-panel">
          <div className="status-panel-body">
            <h2>Run Status</h2>
            <p>{statusMessage}</p>
            <dl>
              <div>
                <dt>Profile sources</dt>
                <dd>{dashboard?.profile_sources.length ?? 0}</dd>
              </div>
              <div>
                <dt>Job leads</dt>
                <dd>{dashboard?.jobs.length ?? 0}</dd>
              </div>
              <div>
                <dt>Drafted applications</dt>
                <dd>{dashboard?.applications.length ?? 0}</dd>
              </div>
            </dl>
          </div>
          <div className="status-footnote">
            <span>Local-first</span>
            <span>Semantic preview before submit</span>
          </div>
        </aside>
      </section>

      <section className="grid two-column">
        <article className="panel">
          <h2>Profile Intake</h2>
          <label className="field">
            <span>CV upload</span>
            <input
              type="file"
              accept=".pdf,.doc,.docx,.txt"
              onChange={(event) => setCvFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button onClick={() => void handleCvUpload()} disabled={busyKey === 'cv-upload'}>
            {busyKey === 'cv-upload' ? 'Parsing CV...' : 'Parse CV'}
          </button>

          <label className="field">
            <span>LinkedIn profile text</span>
            <textarea
              rows={6}
              value={linkedinText}
              onChange={(event) => setLinkedinText(event.target.value)}
              placeholder="Paste profile text or about / experience / skills sections here."
            />
          </label>
          <label className="field">
            <span>LinkedIn export or saved HTML</span>
            <input
              type="file"
              accept=".html,.htm,.txt,.pdf"
              onChange={(event) => setLinkedinFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button
            onClick={() => void handleLinkedinImport()}
            disabled={busyKey === 'linkedin-import'}
          >
            {busyKey === 'linkedin-import' ? 'Merging profile...' : 'Merge LinkedIn Enrichment'}
          </button>

          <div className="source-list">
            <h3>Imported Sources</h3>
            {(dashboard?.profile_sources ?? []).map((source) => (
              <div key={`${source.source_type}-${source.source_label}`} className="source-chip">
                <strong>{source.source_type.toUpperCase()}</strong>
                <span>{source.source_label}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <h2>Manual Profile Review</h2>
          <div className="profile-grid">
            <label className="field">
              <span>Full name</span>
              <input
                value={profileEditor.full_name ?? ''}
                onChange={(event) =>
                  setProfileEditor((current) => ({ ...current, full_name: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Headline</span>
              <input
                value={profileEditor.headline ?? ''}
                onChange={(event) =>
                  setProfileEditor((current) => ({ ...current, headline: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Email</span>
              <input
                value={profileEditor.email ?? ''}
                onChange={(event) =>
                  setProfileEditor((current) => ({ ...current, email: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Location</span>
              <input
                value={profileEditor.location ?? ''}
                onChange={(event) =>
                  setProfileEditor((current) => ({ ...current, location: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>LinkedIn URL</span>
              <input
                type="url"
                placeholder="https://www.linkedin.com/in/your-profile"
                value={profileEditor.links.linkedin ?? ''}
                onChange={(event) => updateProfileLink('linkedin', event.target.value)}
              />
            </label>
            <label className="field">
              <span>GitHub URL</span>
              <input
                type="url"
                placeholder="https://github.com/your-handle"
                value={profileEditor.links.github ?? ''}
                onChange={(event) => updateProfileLink('github', event.target.value)}
              />
            </label>
          </div>
          <label className="field">
            <span>Summary</span>
            <textarea
              rows={5}
              value={profileEditor.summary ?? ''}
              onChange={(event) =>
                setProfileEditor((current) => ({ ...current, summary: event.target.value }))
              }
            />
          </label>
          <label className="field">
            <span>Skills (one per line)</span>
            <textarea
              rows={6}
              value={(profileEditor.skills ?? []).join('\n')}
              onChange={(event) =>
                setProfileEditor((current) => ({
                  ...current,
                  skills: splitLines(event.target.value),
                }))
              }
            />
          </label>
          <label className="field">
            <span>Achievements (one per line)</span>
            <textarea
              rows={5}
              value={(profileEditor.achievements ?? []).join('\n')}
              onChange={(event) =>
                setProfileEditor((current) => ({
                  ...current,
                  achievements: splitLines(event.target.value),
                }))
              }
            />
          </label>
          <button onClick={() => void handleProfileSave()} disabled={busyKey === 'profile-save'}>
            {busyKey === 'profile-save' ? 'Saving...' : 'Save Manual Corrections'}
          </button>
        </article>
      </section>

      <section className="grid two-column">
        <article className="panel">
          <h2>ATS Discovery</h2>
          <label className="field">
            <span>Greenhouse board tokens</span>
            <textarea
              rows={4}
              value={greenhouseBoards}
              onChange={(event) => setGreenhouseBoards(event.target.value)}
            />
          </label>
          <button
            onClick={() => void handleDiscovery('greenhouse')}
            disabled={busyKey === 'discover-greenhouse'}
          >
            {busyKey === 'discover-greenhouse' ? 'Discovering...' : 'Fetch Greenhouse Roles'}
          </button>

          <label className="field">
            <span>Lever company slugs</span>
            <textarea
              rows={4}
              value={leverBoards}
              onChange={(event) => setLeverBoards(event.target.value)}
            />
          </label>
          <button
            onClick={() => void handleDiscovery('lever')}
            disabled={busyKey === 'discover-lever'}
          >
            {busyKey === 'discover-lever' ? 'Discovering...' : 'Fetch Lever Roles'}
          </button>
        </article>

        <article className="panel">
          <h2>LinkedIn Lead Capture</h2>
          <div className="profile-grid">
            <label className="field">
              <span>Company</span>
              <input
                value={manualLead.company}
                onChange={(event) =>
                  setManualLead((current) => ({ ...current, company: event.target.value }))
                }
              />
            </label>
            <label className="field">
              <span>Title</span>
              <input
                value={manualLead.title}
                onChange={(event) =>
                  setManualLead((current) => ({ ...current, title: event.target.value }))
                }
              />
            </label>
          </div>
          <label className="field">
            <span>URL</span>
            <input
              value={manualLead.url}
              onChange={(event) =>
                setManualLead((current) => ({ ...current, url: event.target.value }))
              }
            />
          </label>
          <label className="field">
            <span>Description or notes</span>
            <textarea
              rows={4}
              value={manualLead.description}
              onChange={(event) =>
                setManualLead((current) => ({ ...current, description: event.target.value }))
              }
            />
          </label>
          <button
            onClick={() => void handleLinkedinLeadCapture()}
            disabled={busyKey === 'linkedin-lead'}
          >
            {busyKey === 'linkedin-lead' ? 'Saving lead...' : 'Capture LinkedIn Lead'}
          </button>
        </article>
      </section>

      <section className="panel panel-section">
        <div className="panel-header">
          <div className="panel-title-group">
            <p className="panel-kicker">Shortlist</p>
            <h2>Ranked Jobs</h2>
            <p className="panel-subtitle">
              Fit score combines title alignment, skills, and location compatibility.
            </p>
          </div>
          <div className="header-actions">
            <span className="count-badge">
              {hasShortlistFilters
                ? `${shortlist.length} of ${rankedJobs.length} roles`
                : `${shortlist.length} ${shortlist.length === 1 ? 'role' : 'roles'}`}
            </span>
            <button
              className="button-muted"
              onClick={() => void refreshDashboard()}
              disabled={busyKey !== null}
            >
              Refresh
            </button>
          </div>
        </div>
        <div className="panel-body">
          <div className="shortlist-toolbar">
            <div className="filter-grid">
              <label className="field field-compact">
                <span>Minimum fit score</span>
                <select
                  value={shortlistFilters.minScore}
                  onChange={(event) =>
                    setShortlistFilters((current) => ({
                      ...current,
                      minScore: Number(event.target.value),
                    }))
                  }
                >
                  {fitScoreOptions.map((score) => (
                    <option key={score} value={score}>
                      {score === 0 ? 'Any score' : `${score}+`}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-compact">
                <span>Location</span>
                <input
                  value={shortlistFilters.location}
                  onChange={(event) =>
                    setShortlistFilters((current) => ({
                      ...current,
                      location: event.target.value,
                    }))
                  }
                  placeholder="London, UK"
                />
              </label>
              <div className="field field-compact">
                <span>Workplace</span>
                <div className="filter-pill-row">
                  {[
                    ['all', 'All'],
                    ['remote', 'Remote'],
                    ['hybrid', 'Hybrid'],
                    ['on-site', 'On-site'],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      className={`filter-pill ${shortlistFilters.workplace === value ? 'filter-pill-active' : ''}`}
                      onClick={() =>
                        setShortlistFilters((current) => ({
                          ...current,
                          workplace: value as WorkplaceFilterValue,
                        }))
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            {hasShortlistFilters ? (
              <button
                type="button"
                className="button-secondary shortlist-clear"
                onClick={() =>
                  setShortlistFilters({
                    minScore: 0,
                    location: '',
                    workplace: 'all',
                  })
                }
              >
                Clear filters
              </button>
            ) : null}
          </div>
          {shortlist.length > 0 ? (
            <div className="card-grid card-grid-panel">
              {shortlist.map((job) => (
                <article key={job.id} className="job-card">
                  <div className="job-card-header">
                    <div className="job-card-title-block">
                      <h3>{job.title}</h3>
                      <p className="job-card-company">
                        {job.company} · {formatJobSource(job.source)}
                      </p>
                    </div>
                    <div
                      className="job-score-card"
                      aria-label={`Fit score ${Math.round(job.score ?? 0)} out of 100`}
                    >
                      <span className="job-score-label">Fit score</span>
                      <strong className="job-score-value">{Math.round(job.score ?? 0)}</strong>
                      <span className="job-score-band">{getFitLabel(job.score ?? 0)}</span>
                    </div>
                  </div>
                  <div className="job-meta-row">
                    <span>{job.location || 'Location not listed'}</span>
                    {getWorkplaceLabel(job) ? <span>{getWorkplaceLabel(job)}</span> : null}
                  </div>
                  <p className="job-summary">
                    {job.score_details?.summary ??
                      'Run discovery after uploading a CV to see ranking details.'}
                  </p>
                  {(job.score_details?.matched_signals?.length ?? 0) > 0 ? (
                    <div className="signal-block">
                      <span className="signal-label">Why it matches</span>
                      <div className="tag-row">
                        {(job.score_details?.matched_signals ?? []).slice(0, 4).map((signal) => (
                          <span key={signal} className="tag">
                            {signal}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="signal-block">
                      <span className="signal-label">Key skills</span>
                      <div className="tag-row">
                        {(job.score_details?.matched_skills ?? []).slice(0, 4).map((skill) => (
                          <span key={skill} className="tag">
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {(job.score_details?.missing_signals?.length ?? 0) > 0 ? (
                    <div className="warning-box">
                      <span className="signal-label">Watchouts</span>
                      <p>{(job.score_details?.missing_signals ?? []).slice(0, 2).join(' · ')}</p>
                    </div>
                  ) : null}
                  {job.research?.github_summary || job.research?.website_summary ? (
                    <div className="research-box">
                      <strong>Research</strong>
                      <p>{job.research.website_summary || job.research.github_summary}</p>
                    </div>
                  ) : null}
                  <div className="button-row job-actions">
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer"
                      className="button-secondary"
                    >
                      Open posting
                    </a>
                    <button
                      className="button-secondary"
                      onClick={() => void handleResearch(job.id)}
                      disabled={busyKey === `research-${job.id}`}
                    >
                      {busyKey === `research-${job.id}` ? 'Researching...' : 'Run Research'}
                    </button>
                    <button
                      onClick={() => void handleDraft(job.id)}
                      disabled={busyKey === `draft-${job.id}`}
                    >
                      {busyKey === `draft-${job.id}` ? 'Drafting...' : 'Create Draft'}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : rankedJobs.length > 0 ? (
            <div className="empty-state">
              <p>No roles match the current filters.</p>
              <span>Relax the fit score, location, or workplace filters to widen the shortlist.</span>
            </div>
          ) : (
            <div className="empty-state">
              <p>Shortlist is empty.</p>
              <span>
                Upload a CV, enrich it if needed, and run Greenhouse or Lever discovery to start
                ranking opportunities.
              </span>
            </div>
          )}
        </div>
      </section>

      <section className="grid two-column">
        <article className="panel panel-section">
          <div className="panel-header">
            <div className="panel-title-group">
              <p className="panel-kicker">Workflow</p>
              <h2>Application Drafts</h2>
              <p className="panel-subtitle">
                Draft long-form answers, preview semantic autofill, and only submit after review.
              </p>
            </div>
            <span className="count-badge">
              {(dashboard?.applications ?? []).length}{' '}
              {(dashboard?.applications ?? []).length === 1 ? 'draft' : 'drafts'}
            </span>
          </div>
          <div className="panel-body panel-body-compact">
            {(dashboard?.applications ?? []).length > 0 ? (
              <div className="stack">
                {(dashboard?.applications ?? []).map((application) => {
                  const draftEditor =
                    draftEditors[application.id] ?? createDraftEditorState(application)
                  const linkedJob = jobsById.get(application.job_lead_id)
                  const latestRun = latestRunByApplicationId.get(application.id)
                  const previewKey = `preview-${application.id}`
                  const submitKey = `submit-${application.id}`

                  return (
                    <article key={application.id} className="draft-card">
                      <div className="draft-card-header">
                        <div className="draft-card-title-group">
                          <h3>{linkedJob?.title ?? `Draft #${application.id}`}</h3>
                          <p className="draft-card-company">
                            {linkedJob ? `${linkedJob.company} · ${formatJobSource(linkedJob.source)}` : `Draft #${application.id}`}
                          </p>
                        </div>
                        <span className="count-badge">{formatWorkerStatus(application.status)}</span>
                      </div>
                      <p>{application.tailored_summary}</p>
                      <ul>
                        {application.resume_bullets.map((bullet) => (
                          <li key={bullet}>{bullet}</li>
                        ))}
                      </ul>
                      <label className="field">
                        <span>Cover note</span>
                        <textarea
                          rows={4}
                          value={draftEditor.cover_note}
                          onChange={(event) => updateDraftCoverNote(application.id, event.target.value)}
                        />
                      </label>
                      <div className="screening-answer-list">
                        {draftEditor.screening_answers.map((screeningAnswer, index) => (
                          <label
                            key={`${application.id}-${screeningAnswer.question}`}
                            className="field field-compact"
                          >
                            <span>{screeningAnswer.question}</span>
                            <textarea
                              rows={3}
                              value={screeningAnswer.answer}
                              onChange={(event) =>
                                updateScreeningAnswer(application.id, index, event.target.value)
                              }
                            />
                          </label>
                        ))}
                      </div>
                      {latestRun ? (
                        <div className="draft-run-summary">
                          <span className="count-badge">
                            {latestRun.preview_summary.autofill_ready_count} autofill-ready
                          </span>
                          <span className="count-badge">
                            {latestRun.preview_summary.review_required_count} review items
                          </span>
                        </div>
                      ) : null}
                      <div className="button-row draft-actions">
                        <button
                          className="button-secondary"
                          onClick={() =>
                            void handleWorker(application.id, {
                              dryRun: true,
                              confirmSubmit: false,
                            })
                          }
                          disabled={busyKey === previewKey}
                        >
                          {busyKey === previewKey ? 'Generating preview...' : 'Preview Autofill'}
                        </button>
                        <button
                          onClick={() =>
                            void handleWorker(application.id, {
                              dryRun: false,
                              confirmSubmit: true,
                            })
                          }
                          disabled={busyKey === submitKey}
                        >
                          {busyKey === submitKey ? 'Submitting...' : 'Submit Application'}
                        </button>
                      </div>
                    </article>
                  )
                })}
              </div>
            ) : (
              <div className="empty-state">
                <p>No application drafts yet.</p>
                <span>
                  Drafts appear here after you shortlist a role and generate tailored application
                  content.
                </span>
              </div>
            )}
          </div>
        </article>

        <article className="panel panel-section">
          <div className="panel-header">
            <div className="panel-title-group">
              <p className="panel-kicker">Automation</p>
              <h2>Last Worker Run</h2>
              <p className="panel-subtitle">
                Preview extracted fields, edit hard questions, then rerun or submit with approval.
              </p>
            </div>
            <span className="count-badge">
              {lastWorkerRun ? formatWorkerStatus(lastWorkerRun.status) : 'No run yet'}
            </span>
          </div>
          <div className="panel-body panel-body-compact">
            {lastWorkerRun ? (
              <div className="worker-results">
                <div className="worker-meta-grid">
                  <p>
                    Platform: <strong>{lastWorkerRun.platform}</strong>
                  </p>
                  <p>
                    Status: <strong>{formatWorkerStatus(lastWorkerRun.status)}</strong>
                  </p>
                  <p>
                    Previewed fields: <strong>{lastWorkerRun.preview_summary.total_fields}</strong>
                  </p>
                  <p>
                    Needs review: <strong>{lastWorkerRun.preview_summary.review_required_count}</strong>
                  </p>
                </div>
                <div className="worker-badge-row">
                  <span className="count-badge">
                    {lastWorkerRun.preview_summary.autofill_ready_count} autofill-ready
                  </span>
                  <span className="count-badge">
                    {lastWorkerRun.preview_summary.unresolved_required_count} unresolved required
                  </span>
                  <span className="count-badge">
                    {lastWorkerRun.preview_summary.llm_suggestions_count} LLM suggestions
                  </span>
                </div>
                <p className="muted worker-path">
                  {lastWorkerRun.screenshot_path || 'Screenshot path unavailable.'}
                </p>
                <a
                  href={lastWorkerRun.target_url}
                  target="_blank"
                  rel="noreferrer"
                  className="button-secondary inline-link-button"
                >
                  Open application page
                </a>

                {lastWorkerRun.review_items.length > 0 ? (
                  <div className="worker-review-section">
                    <h3>Review required</h3>
                    <div className="review-grid">
                      {lastWorkerRun.review_items.map((field) => (
                        <article key={field.field_id} className="review-card">
                          <div className="review-card-header">
                            <div>
                              <strong>{getFieldDisplayName(field)}</strong>
                              <p className="muted">
                                {field.required ? 'Required' : 'Optional'} ·{' '}
                                {field.section || field.canonical_label || 'Application question'}
                              </p>
                            </div>
                            <span className="count-badge">
                              {field.answer_source ? formatAnswerSource(field.answer_source) : 'Needs input'}
                            </span>
                          </div>
                          {field.review_reason ? <p className="muted">{field.review_reason}</p> : null}
                          {renderFieldEditor({
                            field,
                            applicationId: currentRunApplicationId,
                            reviewValueLookup,
                            updateReviewOverride,
                          })}
                          <div className="review-card-footer">
                            <span>Confidence {formatConfidence(field.answer_confidence)}</span>
                            <span>{field.classification_source || 'Unclassified'}</span>
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : null}

                {autofillReadyFields.length > 0 ? (
                  <div className="worker-ready-section">
                    <h3>Autofill ready</h3>
                    <div className="tag-row">
                      {autofillReadyFields.slice(0, 8).map((field) => (
                        <span key={field.field_id} className="tag">
                          {getFieldDisplayName(field)}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {lastWorkerRun.actions.length > 0 ? (
                  <div>
                    <h3>Planned actions</h3>
                    <ul>
                      {lastWorkerRun.actions.map((action) => (
                        <li key={`${action.field}-${action.selector}`}>
                          {action.field} via <code>{action.selector}</code>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div>
                  <h3>Logs</h3>
                  <ul>
                    {lastWorkerRun.logs.map((log) => (
                      <li key={log}>{log}</li>
                    ))}
                  </ul>
                </div>

                {currentRunApplicationId ? (
                  <div className="button-row worker-cta-row">
                    <button
                      className="button-secondary"
                      onClick={() =>
                        void handleWorker(currentRunApplicationId, {
                          dryRun: true,
                          confirmSubmit: false,
                        })
                      }
                      disabled={busyKey === `preview-${currentRunApplicationId}`}
                    >
                      {busyKey === `preview-${currentRunApplicationId}`
                        ? 'Refreshing preview...'
                        : 'Refresh Preview'}
                    </button>
                    <button
                      onClick={() =>
                        void handleWorker(currentRunApplicationId, {
                          dryRun: false,
                          confirmSubmit: true,
                        })
                      }
                      disabled={busyKey === `submit-${currentRunApplicationId}`}
                    >
                      {busyKey === `submit-${currentRunApplicationId}`
                        ? 'Submitting...'
                        : 'Submit With Approved Answers'}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="empty-state">
                <p>No worker run yet.</p>
                <span>
                  Preview a draft to inspect semantic field extraction, question matching, and the
                  final approval gate before submission.
                </span>
              </div>
            )}
          </div>
        </article>
      </section>
    </main>
  )
}

export default App

function renderFieldEditor({
  field,
  applicationId,
  reviewValueLookup,
  updateReviewOverride,
}: {
  field: WorkerFieldState
  applicationId: number | null
  reviewValueLookup: Record<string, string>
  updateReviewOverride: (applicationId: number, fieldId: string, value: string) => void
}) {
  if (!applicationId) {
    return null
  }

  const value = reviewValueLookup[field.field_id] ?? field.answer_value ?? ''
  if (field.options.length > 0 && ['select', 'radio', 'checkbox'].includes(field.field_type)) {
    const options = field.options.some((option) => option.value === value || option.label === value)
      ? field.options
      : [...field.options, { label: value || 'Current value', value }]
    return (
      <label className="field field-compact">
        <span>Answer</span>
        <select
          value={value}
          onChange={(event) => updateReviewOverride(applicationId, field.field_id, event.target.value)}
        >
          <option value="">Select an answer</option>
          {options.map((option) => (
            <option key={`${field.field_id}-${option.value}`} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    )
  }

  if (field.field_type === 'textarea' || value.length > 90 || field.question_text.length > 90) {
    return (
      <label className="field field-compact">
        <span>Answer</span>
        <textarea
          rows={4}
          value={value}
          onChange={(event) => updateReviewOverride(applicationId, field.field_id, event.target.value)}
        />
      </label>
    )
  }

  return (
    <label className="field field-compact">
      <span>Answer</span>
      <input
        value={value}
        onChange={(event) => updateReviewOverride(applicationId, field.field_id, event.target.value)}
      />
    </label>
  )
}

function createDraftEditorState(application: ApplicationDraftResponse): DraftEditorState {
  return {
    cover_note: application.cover_note,
    screening_answers: application.screening_answers.map((item) => ({ ...item })),
  }
}

function createDraftEditorStateFromId(
  applicationId: number,
  dashboard: DashboardResponse | null,
): DraftEditorState | null {
  const application = (dashboard?.applications ?? []).find((item) => item.id === applicationId)
  return application ? createDraftEditorState(application) : null
}

function buildAnswerOverrides(
  applicationId: number,
  reviewOverrides: Record<number, Record<string, string>>,
) {
  return Object.entries(reviewOverrides[applicationId] ?? {})
    .map(([field_id, value]) => ({ field_id, value: value.trim() }))
    .filter((item) => item.value.length > 0)
}

function seedReviewOverrides(
  result: WorkerRunResponse,
  setReviewOverrides: Dispatch<SetStateAction<Record<number, Record<string, string>>>>,
) {
  if (!result.application_draft_id) {
    return
  }
  setReviewOverrides((current) => {
    const next = { ...(current[result.application_draft_id!] ?? {}) }
    for (const field of result.review_items) {
      next[field.field_id] = field.answer_value ?? current[result.application_draft_id!]?.[field.field_id] ?? ''
    }
    return { ...current, [result.application_draft_id!]: next }
  })
}

function buildWorkerStatusMessage(result: WorkerRunResponse) {
  if (result.status === 'awaiting_answers') {
    return `Preview found ${result.preview_summary.review_required_count} review item${result.preview_summary.review_required_count === 1 ? '' : 's'} before submission.`
  }
  if (result.status === 'preview_ready') {
    return `Preview ready with ${result.preview_summary.autofill_ready_count} autofill-ready fields.`
  }
  if (result.status === 'ready_for_submit') {
    return 'Fields were filled and the application is ready for final submit review.'
  }
  if (result.status === 'submitted') {
    return 'Application submitted from the approved V2 flow.'
  }
  if (result.status === 'failed') {
    return 'The worker failed while extracting or filling the application.'
  }
  return 'Worker run completed.'
}

function getFieldDisplayName(field: WorkerFieldState) {
  return field.label || field.question_text || field.canonical_label || field.field_id
}

function formatConfidence(value: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function formatAnswerSource(source: string) {
  if (source === 'user_override') {
    return 'Approved'
  }
  if (source === 'screening_answer') {
    return 'Draft answer'
  }
  if (source === 'draft_context') {
    return 'Draft context'
  }
  if (source === 'gemini') {
    return 'Gemini'
  }
  if (source === 'profile_link') {
    return 'Profile link'
  }
  return source.replace(/_/g, ' ')
}

function formatWorkerStatus(status: string) {
  if (status === 'preview_ready') {
    return 'Preview ready'
  }
  if (status === 'awaiting_answers') {
    return 'Needs review'
  }
  if (status === 'ready_for_submit') {
    return 'Ready to submit'
  }
  if (status === 'submitted') {
    return 'Submitted'
  }
  if (status === 'failed') {
    return 'Failed'
  }
  return status.replace(/_/g, ' ')
}

function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function getFitLabel(score: number) {
  if (score >= 80) {
    return 'High'
  }
  if (score >= 60) {
    return 'Medium'
  }
  if (score >= 40) {
    return 'Low'
  }
  return 'Weak'
}

function formatJobSource(source: string) {
  return source.toUpperCase()
}

function getWorkplaceLabel(job: JobLeadResponse) {
  const workplaceType = getWorkplaceType(job)
  if (workplaceType === 'on-site') {
    return 'On-site'
  }
  if (workplaceType === 'remote') {
    return 'Remote'
  }
  if (workplaceType === 'hybrid') {
    return 'Hybrid'
  }
  return null
}

function getWorkplaceType(job: JobLeadResponse): Exclude<WorkplaceFilterValue, 'all'> | null {
  const workplaceSignal = [
    job.employment_type,
    job.location,
    typeof job.metadata_json?.workplaceType === 'string' ? job.metadata_json.workplaceType : '',
  ]
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    .join(' ')
    .toLowerCase()

  if (workplaceSignal.includes('hybrid')) {
    return 'hybrid'
  }
  if (workplaceSignal.includes('remote')) {
    return 'remote'
  }
  if (workplaceSignal.includes('on-site') || workplaceSignal.includes('on site')) {
    return 'on-site'
  }
  return null
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }
  return 'Something went wrong while contacting the API.'
}
