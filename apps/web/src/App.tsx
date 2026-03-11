import {
  type CSSProperties,
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import './App.css'
import {
  assistApplicationDraft,
  buildApiUrl,
  bulkDeleteJobLeads,
  captureLinkedinLead,
  createDraft,
  deleteApplicationDraft,
  deleteJobLead,
  deleteProfileSource,
  deleteWorkerRun,
  discoverGreenhouse,
  discoverLever,
  getDashboard,
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
type ToastTone = 'info' | 'success' | 'warning' | 'error'
type StatusUpdateOptions = {
  tone?: ToastTone
  toast?: boolean
  durationMs?: number
}
type ActionFeedback = StatusUpdateOptions & {
  message: string
}
type ToastNotification = {
  id: number
  message: string
  tone: ToastTone
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
const DEFAULT_MIN_VISIBLE_SCORE = 1
const fitScoreOptions = [DEFAULT_MIN_VISIBLE_SCORE, 0, 40, 50, 60, 70, 80]
const jobHunterLogo = '/assets/icons/pt-job-hunting-logo.png'
const aiImprovementIcon = '/assets/icons/ai-improvement.jpg'

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
  const [pendingDraftJumpId, setPendingDraftJumpId] = useState<number | null>(null)
  const [highlightedDraftId, setHighlightedDraftId] = useState<number | null>(null)
  const [expandedJobIds, setExpandedJobIds] = useState<Record<number, boolean>>({})
  const [toasts, setToasts] = useState<ToastNotification[]>([])
  const [isShortlistCollapsed, setIsShortlistCollapsed] = useState(false)
  const [showAppliedJobs, setShowAppliedJobs] = useState(false)
  const [shortlistFilters, setShortlistFilters] = useState<{
    minScore: number
    location: string
    workplace: WorkplaceFilterValue
  }>({
    minScore: DEFAULT_MIN_VISIBLE_SCORE,
    location: '',
    workplace: 'all',
  })
  const toastTimeoutsRef = useRef<Record<number, number>>({})

  const scrollToElement = useCallback((element: HTMLElement | null, focusSelector?: string) => {
    if (!element) {
      return false
    }
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    if (focusSelector) {
      window.setTimeout(() => {
        const focusTarget = element.querySelector(focusSelector) as HTMLElement | null
        focusTarget?.focus()
      }, 220)
    }
    return true
  }, [])

  const jumpToSection = useCallback((sectionId: string) => {
    return scrollToElement(document.getElementById(sectionId))
  }, [scrollToElement])

  const jumpToDraft = useCallback((applicationId: number) => {
    const draftElement = document.getElementById(`application-draft-${applicationId}`)
    if (!draftElement) {
      return false
    }
    setHighlightedDraftId(applicationId)
    return scrollToElement(draftElement, 'textarea, input')
  }, [scrollToElement])

  const jumpToJob = useCallback((jobId: number) => {
    setIsShortlistCollapsed(false)
    setExpandedJobIds((current) => (current[jobId] ? current : { ...current, [jobId]: true }))
    window.setTimeout(() => {
      void scrollToElement(
        document.getElementById(`job-lead-${jobId}`) ?? document.getElementById('shortlist-section'),
      )
    }, 160)
  }, [scrollToElement])

  const dismissToast = useCallback((toastId: number) => {
    const timeoutId = toastTimeoutsRef.current[toastId]
    if (timeoutId) {
      window.clearTimeout(timeoutId)
      delete toastTimeoutsRef.current[toastId]
    }
    setToasts((current) => current.filter((toast) => toast.id !== toastId))
  }, [])

  const pushToast = useCallback(
    (message: string, tone: ToastTone, options?: Pick<StatusUpdateOptions, 'durationMs'>) => {
      const nextMessage = message.trim()
      if (!nextMessage) {
        return
      }

      const toastId = Date.now() + Math.round(Math.random() * 1000)
      setToasts((current) => [...current, { id: toastId, message: nextMessage, tone }].slice(-4))

      const durationMs =
        options?.durationMs ?? (tone === 'error' ? 8000 : tone === 'warning' ? 6500 : 4200)
      if (durationMs > 0) {
        toastTimeoutsRef.current[toastId] = window.setTimeout(() => {
          dismissToast(toastId)
        }, durationMs)
      }
    },
    [dismissToast],
  )

  const updateStatus = useCallback(
    (message: string, options: StatusUpdateOptions = {}) => {
      const tone = options.tone ?? 'info'
      setStatusMessage(message)

      const shouldToast = options.toast ?? (tone === 'error' || tone === 'warning')
      if (shouldToast) {
        pushToast(message, tone, { durationMs: options.durationMs })
      }
    },
    [pushToast],
  )

  useEffect(() => {
    return () => {
      for (const timeoutId of Object.values(toastTimeoutsRef.current)) {
        window.clearTimeout(timeoutId)
      }
      toastTimeoutsRef.current = {}
    }
  }, [])

  useEffect(() => {
    void refreshDashboard()
  }, [])

  useEffect(() => {
    if (dashboard?.profile?.merged_profile) {
      setProfileEditor(normalizeProfileEditor(dashboard.profile.merged_profile))
    }
  }, [dashboard?.profile])

  useEffect(() => {
    if (!dashboard?.applications) {
      return
    }
    setDraftEditors((current) => {
      const applicationIds = new Set(dashboard.applications.map((application) => application.id))
      const next = Object.fromEntries(
        Object.entries(current).filter(([applicationId]) => applicationIds.has(Number(applicationId))),
      )
      for (const application of dashboard.applications) {
        if (!next[application.id]) {
          next[application.id] = createDraftEditorState(application)
        }
      }
      return next
    })
    setReviewOverrides((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([applicationId]) =>
          dashboard.applications.some((application) => application.id === Number(applicationId)),
        ),
      ),
    )
  }, [dashboard?.applications])

  useEffect(() => {
    if (!dashboard?.jobs) {
      return
    }
    const jobIds = new Set(dashboard.jobs.map((job) => job.id))
    setExpandedJobIds((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([jobId]) => jobIds.has(Number(jobId))),
      ),
    )
  }, [dashboard?.jobs])

  useEffect(() => {
    const latestRun = dashboard?.worker_runs?.[0] ?? null
    if ((latestRun?.id ?? null) !== (lastWorkerRun?.id ?? null)) {
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

  useEffect(() => {
    if (!pendingDraftJumpId) {
      return
    }

    if (!jumpToDraft(pendingDraftJumpId)) {
      return
    }
    setPendingDraftJumpId(null)
  }, [pendingDraftJumpId, dashboard?.applications, jumpToDraft])

  useEffect(() => {
    if (!highlightedDraftId) {
      return
    }

    const timeoutId = window.setTimeout(() => {
      setHighlightedDraftId((current) => (current === highlightedDraftId ? null : current))
    }, 2200)
    return () => window.clearTimeout(timeoutId)
  }, [highlightedDraftId])

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

  const latestApplicationByJobId = useMemo(() => {
    const next = new Map<number, ApplicationDraftResponse>()
    for (const application of dashboard?.applications ?? []) {
      if (!next.has(application.job_lead_id)) {
        next.set(application.job_lead_id, application)
      }
    }
    return next
  }, [dashboard?.applications])

  const filteredShortlist = useMemo(() => {
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

  const appliedShortlistCount = useMemo(() => {
    return filteredShortlist.filter((job) =>
      isRecordedApplicationStatus(getTrackedJobStatus(job, latestApplicationByJobId.get(job.id))),
    ).length
  }, [filteredShortlist, latestApplicationByJobId])

  const shortlist = useMemo(() => {
    return filteredShortlist
      .filter((job) => {
        if (showAppliedJobs) {
          return true
        }
        return !isRecordedApplicationStatus(getTrackedJobStatus(job, latestApplicationByJobId.get(job.id)))
      })
      .sort((left, right) => {
        const leftPriority = getShortlistJobPriority(
          getTrackedJobStatus(left, latestApplicationByJobId.get(left.id)),
        )
        const rightPriority = getShortlistJobPriority(
          getTrackedJobStatus(right, latestApplicationByJobId.get(right.id)),
        )
        if (leftPriority !== rightPriority) {
          return leftPriority - rightPriority
        }
        return (right.score ?? 0) - (left.score ?? 0)
      })
  }, [filteredShortlist, latestApplicationByJobId, showAppliedJobs])

  const hasShortlistFilters =
    shortlistFilters.minScore !== DEFAULT_MIN_VISIBLE_SCORE ||
    shortlistFilters.location.trim().length > 0 ||
    shortlistFilters.workplace !== 'all'
  const canBulkDeleteFilteredJobs = hasShortlistFilters && shortlist.length > 0
  const submittedApplicationsCount = useMemo(() => {
    return (dashboard?.applications ?? []).filter((application) => application.status === 'submitted')
      .length
  }, [dashboard?.applications])
  const currentRunDraft = useMemo(() => {
    const applicationId = lastWorkerRun?.application_draft_id
    if (!applicationId) {
      return null
    }
    return (dashboard?.applications ?? []).find((application) => application.id === applicationId) ?? null
  }, [dashboard?.applications, lastWorkerRun?.application_draft_id])
  const currentRunJob = currentRunDraft ? jobsById.get(currentRunDraft.job_lead_id) ?? null : null
  const statusNavItems = [
    {
      label: 'Profile sources',
      value: dashboard?.profile_sources.length ?? 0,
      targetId: 'profile-section',
    },
    {
      label: 'Job leads',
      value: dashboard?.jobs.length ?? 0,
      targetId: 'shortlist-section',
    },
    {
      label: 'Drafted applications',
      value: dashboard?.applications.length ?? 0,
      targetId: 'application-drafts-section',
    },
    {
      label: 'Applications sent',
      value: submittedApplicationsCount,
      targetId: 'worker-run-section',
    },
  ]

  async function refreshDashboard(
    nextMessage = 'Dashboard is up to date.',
    options: StatusUpdateOptions = {},
  ) {
    try {
      const nextDashboard = await getDashboard()
      setDashboard(nextDashboard)
      updateStatus(nextMessage, options)
    } catch (error) {
      updateStatus(getErrorMessage(error), { tone: 'error', toast: true, durationMs: 8000 })
    }
  }

  async function runAction(key: string, action: () => Promise<ActionFeedback | string | void>) {
    try {
      setBusyKey(key)
      const result = await action()
      const feedback: ActionFeedback =
        typeof result === 'string'
          ? { message: result }
          : result ?? { message: 'Dashboard is up to date.' }
      await refreshDashboard(feedback.message, feedback)
    } catch (error) {
      updateStatus(getErrorMessage(error), { tone: 'error', toast: true, durationMs: 8000 })
    } finally {
      setBusyKey(null)
    }
  }

  async function handleCvUpload() {
    if (!cvFile) {
      updateStatus('Choose a CV file before uploading.', { tone: 'warning', toast: true })
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
      updateStatus('Paste LinkedIn text or attach an exported file first.', {
        tone: 'warning',
        toast: true,
      })
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

  async function handleDeleteProfileSource(sourceId: number, sourceLabel: string) {
    const confirmed = window.confirm(
      `Delete imported source "${sourceLabel}"? This will remove it from the merged profile state.`,
    )
    if (!confirmed) {
      return
    }

    await runAction(`delete-source-${sourceId}`, async () => {
      const result = await deleteProfileSource(sourceId)
      return `Deleted imported profile source "${sourceLabel}". ${buildDeleteStatusMessage(result)}`
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
      updateStatus('LinkedIn lead capture requires a company and job title.', {
        tone: 'warning',
        toast: true,
      })
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

  async function handleDraft(jobId: number) {
    const busyLabel = `draft-${jobId}`
    try {
      setBusyKey(busyLabel)
      const draft = await createDraft(jobId)
      setPendingDraftJumpId(draft.id)
      await refreshDashboard(`Created an application draft for job ${jobId}. Jumped to the draft editor.`, {
        tone: 'success',
        toast: true,
      })
    } catch (error) {
      updateStatus(getErrorMessage(error), { tone: 'error', toast: true, durationMs: 8000 })
    } finally {
      setBusyKey(null)
    }
  }

  async function handleDeleteJob(jobId: number) {
    const confirmed = window.confirm(
      'Delete this job lead? Any linked drafts and worker runs will be removed as well.',
    )
    if (!confirmed) {
      return
    }

    await runAction(`delete-job-${jobId}`, async () => {
      const result = await deleteJobLead(jobId)
      return buildDeleteStatusMessage(result)
    })
  }

  async function handleDeleteFilteredJobs() {
    if (!hasShortlistFilters) {
      updateStatus('Apply at least one shortlist filter before using bulk delete.', {
        tone: 'warning',
        toast: true,
      })
      return
    }
    if (shortlist.length === 0) {
      updateStatus('No filtered leads match the current filters.', {
        tone: 'warning',
        toast: true,
      })
      return
    }

    const confirmed = window.confirm(
      `Delete ${shortlist.length} filtered lead${shortlist.length === 1 ? '' : 's'}? Linked drafts and worker runs will be removed as well.`,
    )
    if (!confirmed) {
      return
    }

    await runAction('delete-filtered-jobs', async () => {
      const result = await bulkDeleteJobLeads(shortlist.map((job) => job.id))
      return buildBulkDeleteStatusMessage(result)
    })
  }

  function toggleJobExpansion(jobId: number) {
    setExpandedJobIds((current) => ({
      ...current,
      [jobId]: !current[jobId],
    }))
  }

  async function handleDeleteApplication(applicationId: number) {
    const confirmed = window.confirm(
      'Delete this application draft? Related worker runs will be removed too.',
    )
    if (!confirmed) {
      return
    }

    await runAction(`delete-application-${applicationId}`, async () => {
      const result = await deleteApplicationDraft(applicationId)
      return buildDeleteStatusMessage(result)
    })
  }

  async function handleDeleteLastWorkerRun() {
    if (!lastWorkerRun) {
      return
    }

    const confirmed = window.confirm(
      'Delete this worker run? The draft will stay in place.',
    )
    if (!confirmed) {
      return
    }

    await runAction(`delete-run-${lastWorkerRun.id}`, async () => {
      const result = await deleteWorkerRun(lastWorkerRun.id)
      return buildDeleteStatusMessage(result)
    })
  }

  function applyUpdatedDraft(updatedDraft: ApplicationDraftResponse) {
    setDashboard((current) => {
      if (!current) {
        return current
      }
      return {
        ...current,
        applications: current.applications.map((application) =>
          application.id === updatedDraft.id ? updatedDraft : application,
        ),
      }
    })
    setDraftEditors((current) => ({
      ...current,
      [updatedDraft.id]: createDraftEditorState(updatedDraft),
    }))
  }

  async function requestDraftAssist(
    busyKeyValue: string,
    applicationId: number,
    payload: {
      target: 'cover_note' | 'question_answer'
      question?: string
      current_text?: string
      persist?: boolean
    },
    onComplete?: (text: string) => void,
  ) {
    try {
      setBusyKey(busyKeyValue)
      const result = await assistApplicationDraft(applicationId, payload)
      if (result.updated_draft) {
        applyUpdatedDraft(result.updated_draft)
      }
      onComplete?.(result.text)
      const subject =
        payload.target === 'cover_note'
          ? 'cover note'
          : (payload.question ?? 'question answer').toLowerCase()
      updateStatus(`AI refreshed the ${subject}. ${result.reasoning}`, { tone: 'success' })
    } catch (error) {
      updateStatus(getErrorMessage(error), { tone: 'error', toast: true, durationMs: 8000 })
    } finally {
      setBusyKey(null)
    }
  }

  async function handleWorker(
    applicationId: number,
    options: { dryRun: boolean; confirmSubmit: boolean },
  ) {
    const editor = draftEditors[applicationId] ?? createDraftEditorStateFromId(applicationId, dashboard)
    if (!editor) {
      updateStatus(`Draft ${applicationId} is no longer available.`, {
        tone: 'warning',
        toast: true,
      })
      return
    }

    const busyLabel = options.confirmSubmit ? `submit-${applicationId}` : `preview-${applicationId}`
    let completedRun: WorkerRunResponse | null = null
    await runAction(busyLabel, async () => {
      const result = await runWorker(applicationId, {
        dry_run: options.dryRun,
        confirm_submit: options.confirmSubmit,
        cover_note: editor.cover_note,
        screening_answers: editor.screening_answers,
        answer_overrides: buildAnswerOverrides(applicationId, reviewOverrides),
      })
      completedRun = result
      setLastWorkerRun(result)
      seedReviewOverrides(result, setReviewOverrides)
      return {
        message: buildWorkerStatusMessage(result),
        tone: getWorkerToastTone(result, options.confirmSubmit),
        toast: true,
      }
    })
    if (completedRun) {
      jumpToSection('worker-run-section')
    }
  }

  async function handleAssistCoverNote(applicationId: number) {
    const editor = draftEditors[applicationId] ?? createDraftEditorStateFromId(applicationId, dashboard)
    if (!editor) {
      updateStatus(`Draft ${applicationId} is no longer available.`, {
        tone: 'warning',
        toast: true,
      })
      return
    }
    await requestDraftAssist(`ai-cover-${applicationId}`, applicationId, {
      target: 'cover_note',
      current_text: editor.cover_note,
      persist: true,
    })
  }

  async function handleAssistScreeningAnswer(
    applicationId: number,
    question: string,
    answer: string,
    index: number,
  ) {
    await requestDraftAssist(`ai-screening-${applicationId}-${index}`, applicationId, {
      target: 'question_answer',
      question,
      current_text: answer,
      persist: true,
    })
  }

  async function handleAssistReviewField(applicationId: number, field: WorkerFieldState) {
    const currentValue =
      reviewOverrides[applicationId]?.[field.field_id] ?? field.answer_value ?? ''
    const target = field.canonical_key === 'cover_note' ? 'cover_note' : 'question_answer'
    const question =
      target === 'question_answer'
        ? field.question_text || field.label || getFieldDisplayName(field)
        : undefined

    await requestDraftAssist(
      `ai-field-${applicationId}-${field.field_id}`,
      applicationId,
      {
        target,
        question,
        current_text: currentValue,
        persist: true,
      },
      (text) => updateReviewOverride(applicationId, field.field_id, text),
    )
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
      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`toast toast-${toast.tone}`}
            role={toast.tone === 'error' ? 'alert' : 'status'}
          >
            <div className="toast-copy">
              <span className="toast-label">{getToastToneLabel(toast.tone)}</span>
              <p>{toast.message}</p>
            </div>
            <button
              type="button"
              className="toast-dismiss"
              onClick={() => dismissToast(toast.id)}
              aria-label="Dismiss notification"
            >
              Dismiss
            </button>
          </div>
        ))}
      </div>

      <section className="hero">
        <div className="panel hero-panel">
          <div className="brand-lockup">
            <img
              src={jobHunterLogo}
              alt="PT x Job Hunting logo"
              className="brand-logo"
            />
            <div className="brand-meta">
              <p className="eyebrow">PT x</p>
              <p className="brand-name">Job Hunting</p>
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
            <div className="status-nav-grid">
              {statusNavItems.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="status-nav-item"
                  onClick={() => jumpToSection(item.targetId)}
                >
                  <span className="status-nav-label">{item.label}</span>
                  <strong className="status-nav-value">{item.value}</strong>
                  <span className="status-nav-hint">Open section</span>
                </button>
              ))}
            </div>
          </div>
          <div className="status-footnote">
            <span>Local-first</span>
            <span>Semantic preview before submit</span>
          </div>
        </aside>
      </section>

      <section className="grid two-column" id="profile-section">
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
              <div key={source.id ?? `${source.source_type}-${source.source_label}`} className="source-chip">
                <div className="source-chip-meta">
                  <strong>{source.source_type.toUpperCase()}</strong>
                  <span>{source.source_label}</span>
                </div>
                {source.id ? (
                  <button
                    type="button"
                    className="button-danger button-small"
                    onClick={() => void handleDeleteProfileSource(source.id!, source.source_label)}
                    disabled={busyKey === `delete-source-${source.id}`}
                  >
                    {busyKey === `delete-source-${source.id}` ? 'Deleting...' : 'Delete'}
                  </button>
                ) : null}
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

      <section className="panel panel-section" id="shortlist-section">
        <div className="panel-header">
          <div className="panel-title-group">
            <p className="panel-kicker">Shortlist</p>
            <h2>Ranked Jobs</h2>
            <p className="panel-subtitle">
              Fit score combines title alignment, skills, and location compatibility. Applied roles
              are tracked separately so you can avoid duplicate work.
            </p>
          </div>
          <div className="header-actions">
            <span className="count-badge">
              {hasShortlistFilters
                ? `${shortlist.length} of ${rankedJobs.length} roles`
                : `${shortlist.length} ${shortlist.length === 1 ? 'role' : 'roles'}`}
            </span>
            {appliedShortlistCount > 0 ? (
              <span className="count-badge">
                {appliedShortlistCount} applied {showAppliedJobs ? 'shown' : 'hidden'}
              </span>
            ) : null}
            <button
              className="button-muted"
              onClick={() => void refreshDashboard()}
              disabled={busyKey !== null}
            >
              Refresh
            </button>
            <button
              type="button"
              className="button-muted"
              onClick={() => setIsShortlistCollapsed((current) => !current)}
            >
              {isShortlistCollapsed ? 'Expand' : 'Collapse'}
            </button>
          </div>
        </div>
        {!isShortlistCollapsed ? (
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
                      {score === DEFAULT_MIN_VISIBLE_SCORE
                        ? 'Hide 0 scores'
                        : score === 0
                          ? 'Show all scores'
                          : `${score}+`}
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
            {appliedShortlistCount > 0 || hasShortlistFilters ? (
              <div className="shortlist-actions">
                {appliedShortlistCount > 0 ? (
                  <button
                    type="button"
                    className="button-secondary shortlist-clear"
                    onClick={() => setShowAppliedJobs((current) => !current)}
                  >
                    {showAppliedJobs
                      ? `Hide ${appliedShortlistCount} applied`
                      : `Show ${appliedShortlistCount} applied`}
                  </button>
                ) : null}
                {hasShortlistFilters ? (
                  <>
                    <button
                      type="button"
                      className="button-secondary shortlist-clear"
                      onClick={() =>
                        setShortlistFilters({
                          minScore: DEFAULT_MIN_VISIBLE_SCORE,
                          location: '',
                          workplace: 'all',
                        })
                      }
                    >
                      Clear filters
                    </button>
                    <button
                      type="button"
                      className="button-danger shortlist-clear"
                      onClick={() => void handleDeleteFilteredJobs()}
                      disabled={!canBulkDeleteFilteredJobs || busyKey === 'delete-filtered-jobs'}
                    >
                      {busyKey === 'delete-filtered-jobs'
                        ? 'Deleting...'
                        : `Delete ${shortlist.length} filtered ${shortlist.length === 1 ? 'lead' : 'leads'}`}
                    </button>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
          {shortlist.length > 0 ? (
            <div className="card-grid card-grid-panel">
              {shortlist.map((job) => {
                const isExpanded = expandedJobIds[job.id] ?? false
                const fitScore = Math.round(job.score ?? 0)
                const linkedApplication = latestApplicationByJobId.get(job.id) ?? null
                const trackedJobStatus = getTrackedJobStatus(job, linkedApplication)
                const isAppliedJob = isRecordedApplicationStatus(trackedJobStatus)
                return (
                  <article
                    key={job.id}
                    id={`job-lead-${job.id}`}
                    className={`job-card ${isExpanded ? 'job-card-expanded' : 'job-card-collapsed'} ${isAppliedJob ? 'job-card-applied' : trackedJobStatus ? 'job-card-tracked' : ''}`.trim()}
                  >
                    <div className="job-card-header">
                      <div className="job-card-title-block">
                        <h3>{job.title}</h3>
                        <p className="job-card-company">
                          {job.company} · {formatJobSource(job.source)}
                        </p>
                        {trackedJobStatus ? (
                          <div className="job-card-status-row">
                            <span className={getWorkerStatusBadgeClassName(trackedJobStatus)}>
                              {formatWorkerStatus(trackedJobStatus)}
                            </span>
                          </div>
                        ) : null}
                      </div>
                      <div
                        className="job-score-card"
                        aria-label={`Fit score ${fitScore} out of 100`}
                        style={getFitScoreCardStyle(fitScore)}
                      >
                        <span className="job-score-label">Fit score</span>
                        <strong className="job-score-value">{fitScore}</strong>
                        <span className="job-score-band">{getFitLabel(fitScore)}</span>
                      </div>
                    </div>
                    <div className="job-meta-row">
                      <span>{job.location || 'Location not listed'}</span>
                      {getWorkplaceLabel(job) ? <span>{getWorkplaceLabel(job)}</span> : null}
                    </div>
                    <p className={`job-summary ${isExpanded ? '' : 'job-summary-collapsed'}`.trim()}>
                      {job.score_details?.summary ??
                        'Run discovery after uploading a CV to see ranking details.'}
                    </p>
                    {isExpanded ? (
                      <>
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
                      </>
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
                      {linkedApplication ? (
                        <button
                          type="button"
                          className="button-secondary"
                          onClick={() => jumpToDraft(linkedApplication.id)}
                        >
                          Open draft
                        </button>
                      ) : isAppliedJob ? (
                        <button type="button" className="button-secondary" disabled>
                          Application recorded
                        </button>
                      ) : (
                        <button
                          onClick={() => void handleDraft(job.id)}
                          disabled={busyKey === `draft-${job.id}`}
                        >
                          {busyKey === `draft-${job.id}` ? 'Drafting...' : 'Create Draft'}
                        </button>
                      )}
                      <button
                        type="button"
                        className="button-secondary"
                        onClick={() => toggleJobExpansion(job.id)}
                      >
                        {isExpanded ? 'Hide details' : 'Show details'}
                      </button>
                    </div>
                    {isExpanded ? (
                      <div className="job-card-footer-actions">
                        <button
                          type="button"
                          className="button-danger"
                          onClick={() => void handleDeleteJob(job.id)}
                          disabled={busyKey === `delete-job-${job.id}`}
                        >
                          {busyKey === `delete-job-${job.id}` ? 'Deleting...' : 'Delete Lead'}
                        </button>
                      </div>
                    ) : null}
                  </article>
              )})}
            </div>
          ) : filteredShortlist.length > 0 && appliedShortlistCount > 0 && !showAppliedJobs ? (
            <div className="empty-state">
              <p>Only tracked applications match the current shortlist.</p>
              <span>Use "Show applied" to review greyed-out roles that already have a recorded application state.</span>
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
        ) : null}
      </section>

      <section className="grid two-column">
        <article className="panel panel-section" id="application-drafts-section">
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
                    <article
                      key={application.id}
                      id={`application-draft-${application.id}`}
                      className={`draft-card ${highlightedDraftId === application.id ? 'draft-card-highlighted' : ''}`}
                    >
                      <div className="draft-card-header">
                        <div className="draft-card-title-group">
                          <h3>{linkedJob?.title ?? `Draft #${application.id}`}</h3>
                          <p className="draft-card-company">
                            {linkedJob ? `${linkedJob.company} · ${formatJobSource(linkedJob.source)}` : `Draft #${application.id}`}
                          </p>
                        </div>
                        <span className={getWorkerStatusBadgeClassName(application.status)}>
                          {formatWorkerStatus(application.status)}
                        </span>
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
                      <div className="field-actions">
                        <button
                          type="button"
                          className="button-secondary button-small"
                          onClick={() => void handleAssistCoverNote(application.id)}
                          disabled={busyKey === `ai-cover-${application.id}`}
                        >
                          <AiAssistLabel
                            busy={busyKey === `ai-cover-${application.id}`}
                            hasExistingText={draftEditor.cover_note.trim().length > 0}
                          />
                        </button>
                      </div>
                      <div className="screening-answer-list">
                        {draftEditor.screening_answers.map((screeningAnswer, index) => (
                          <div
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
                            <div className="field-actions">
                              <button
                                type="button"
                                className="button-secondary button-small"
                                onClick={() =>
                                  void handleAssistScreeningAnswer(
                                    application.id,
                                    screeningAnswer.question,
                                    screeningAnswer.answer,
                                    index,
                                  )
                                }
                                disabled={busyKey === `ai-screening-${application.id}-${index}`}
                              >
                                <AiAssistLabel
                                  busy={busyKey === `ai-screening-${application.id}-${index}`}
                                  hasExistingText={screeningAnswer.answer.trim().length > 0}
                                />
                              </button>
                            </div>
                          </div>
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
                      {latestRun || linkedJob ? (
                        <div className="field-actions">
                          {latestRun ? (
                            <button
                              type="button"
                              className="button-secondary button-small"
                              onClick={() => jumpToSection('worker-run-section')}
                            >
                              Open latest run
                            </button>
                          ) : null}
                          {linkedJob ? (
                            <button
                              type="button"
                              className="button-secondary button-small"
                              onClick={() => jumpToJob(linkedJob.id)}
                            >
                              Open linked role
                            </button>
                          ) : null}
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
                        <button
                          type="button"
                          className="button-danger"
                          onClick={() => void handleDeleteApplication(application.id)}
                          disabled={busyKey === `delete-application-${application.id}`}
                        >
                          {busyKey === `delete-application-${application.id}`
                            ? 'Deleting...'
                            : 'Delete Draft'}
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

        <article className="panel panel-section" id="worker-run-section">
          <div className="panel-header">
            <div className="panel-title-group">
              <p className="panel-kicker">Automation</p>
              <h2>Last Worker Run</h2>
              <p className="panel-subtitle">
                Preview extracted fields, edit hard questions, then rerun or submit with approval.
              </p>
            </div>
            <span className={getWorkerStatusBadgeClassName(lastWorkerRun?.status)}>
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
                {lastWorkerRun.screenshot_path ? (
                  <div className="worker-artifact-card">
                    <div className="worker-artifact-copy">
                      <span className="signal-label">Screenshot</span>
                      <p
                        className="muted worker-artifact-name"
                        title={lastWorkerRun.screenshot_path}
                      >
                        {formatArtifactFileName(lastWorkerRun.screenshot_path)}
                      </p>
                    </div>
                    <a
                      href={buildApiUrl(`/api/applications/runs/${lastWorkerRun.id}/screenshot`)}
                      target="_blank"
                      rel="noreferrer"
                      className="button-secondary button-small inline-link-button"
                    >
                      Open screenshot
                    </a>
                  </div>
                ) : (
                  <p className="muted worker-path">Screenshot unavailable.</p>
                )}
                <a
                  href={lastWorkerRun.target_url}
                  target="_blank"
                  rel="noreferrer"
                  className="button-secondary inline-link-button"
                >
                  Open application page
                </a>
                {currentRunApplicationId || currentRunJob ? (
                  <div className="worker-link-row">
                    {currentRunApplicationId ? (
                      <button
                        type="button"
                        className="button-secondary button-small"
                        onClick={() => jumpToDraft(currentRunApplicationId)}
                      >
                        Open linked draft
                      </button>
                    ) : null}
                    {currentRunJob ? (
                      <button
                        type="button"
                        className="button-secondary button-small"
                        onClick={() => jumpToJob(currentRunJob.id)}
                      >
                        Open linked role
                      </button>
                    ) : null}
                  </div>
                ) : null}

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
                          {currentRunApplicationId && canAssistField(field) ? (
                            <div className="field-actions">
                              <button
                                type="button"
                                className="button-secondary button-small"
                                onClick={() =>
                                  void handleAssistReviewField(currentRunApplicationId, field)
                                }
                                disabled={
                                  busyKey === `ai-field-${currentRunApplicationId}-${field.field_id}`
                                }
                              >
                                <AiAssistLabel
                                  busy={
                                    busyKey === `ai-field-${currentRunApplicationId}-${field.field_id}`
                                  }
                                  hasExistingText={
                                    (
                                      reviewValueLookup[field.field_id] ??
                                      field.answer_value ??
                                      ''
                                    ).trim().length > 0
                                  }
                                />
                              </button>
                            </div>
                          ) : null}
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
                    <button
                      type="button"
                      className="button-danger"
                      onClick={() => void handleDeleteLastWorkerRun()}
                      disabled={busyKey === `delete-run-${lastWorkerRun.id}`}
                    >
                      {busyKey === `delete-run-${lastWorkerRun.id}` ? 'Deleting...' : 'Delete This Run'}
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

function AiAssistLabel({
  busy,
  hasExistingText,
}: {
  busy: boolean
  hasExistingText: boolean
}) {
  return (
    <>
      <img src={aiImprovementIcon} alt="" aria-hidden="true" className="button-icon" />
      <span>{busy ? 'Drafting...' : hasExistingText ? 'Improve with AI' : 'Draft with AI'}</span>
    </>
  )
}

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
    if (result.logs.some((log) => log.includes('skipped final submit'))) {
      return 'Application was not sent because at least one field could not be applied.'
    }
    if (result.logs.some((log) => log.includes('Submit button was not detected'))) {
      return 'Application was not sent. Fields were filled, but the submit button was not detected.'
    }
    return 'Fields were filled and the application is ready for final submit review.'
  }
  if (result.status === 'submit_clicked') {
    return 'Submit was clicked, but ATS confirmation was not detected. Review the final page state.'
  }
  if (result.status === 'submitted') {
    return 'Application submission was confirmed by the ATS.'
  }
  if (result.status === 'failed') {
    return 'The worker failed while extracting or filling the application.'
  }
  return 'Worker run completed.'
}

function getWorkerToastTone(result: WorkerRunResponse, requestedSubmit: boolean): ToastTone {
  if (result.status === 'submitted') {
    return 'success'
  }
  if (result.status === 'submit_clicked') {
    return 'warning'
  }
  if (result.status === 'failed') {
    return 'error'
  }
  if (result.status === 'awaiting_answers') {
    return 'warning'
  }
  if (result.status === 'ready_for_submit') {
    if (
      result.logs.some(
        (log) =>
          log.includes('skipped final submit') || log.includes('Submit button was not detected'),
      )
    ) {
      return 'error'
    }
    return requestedSubmit ? 'warning' : 'success'
  }
  return 'success'
}

function getToastToneLabel(tone: ToastTone) {
  if (tone === 'error') {
    return 'Error'
  }
  if (tone === 'warning') {
    return 'Needs attention'
  }
  if (tone === 'success') {
    return 'Completed'
  }
  return 'Update'
}

function buildDeleteStatusMessage(result: {
  entity: 'job_lead' | 'application_draft' | 'worker_run' | 'profile_source'
  deleted_counts: Record<string, number>
}) {
  if (result.entity === 'job_lead') {
    const draftCount = result.deleted_counts.application_drafts ?? 0
    const runCount = result.deleted_counts.worker_runs ?? 0
    return `Deleted job lead and cleaned up ${draftCount} draft${draftCount === 1 ? '' : 's'} plus ${runCount} worker run${runCount === 1 ? '' : 's'}.`
  }
  if (result.entity === 'application_draft') {
    const runCount = result.deleted_counts.worker_runs ?? 0
    return `Deleted application draft and removed ${runCount} worker run${runCount === 1 ? '' : 's'}.`
  }
  if (result.entity === 'profile_source') {
    const remainingCount = result.deleted_counts.remaining_sources ?? 0
    return `${remainingCount} imported source${remainingCount === 1 ? '' : 's'} remaining.`
  }
  return 'Deleted worker run.'
}

function buildBulkDeleteStatusMessage(result: {
  deleted_counts: Record<string, number>
  deleted_ids: number[]
}) {
  const leadCount = result.deleted_counts.job_leads ?? result.deleted_ids.length
  const draftCount = result.deleted_counts.application_drafts ?? 0
  const runCount = result.deleted_counts.worker_runs ?? 0
  return `Deleted ${leadCount} filtered lead${leadCount === 1 ? '' : 's'} and cleaned up ${draftCount} draft${draftCount === 1 ? '' : 's'} plus ${runCount} worker run${runCount === 1 ? '' : 's'}.`
}

function getTrackedJobStatus(
  job: JobLeadResponse,
  linkedApplication?: ApplicationDraftResponse | null,
) {
  if (linkedApplication?.status) {
    return linkedApplication.status
  }
  return isRecordedApplicationStatus(job.status) ? job.status : null
}

function isRecordedApplicationStatus(status?: string | null) {
  return status === 'submitted' || status === 'submit_clicked'
}

function getShortlistJobPriority(status?: string | null) {
  if (!status) {
    return 0
  }
  if (isRecordedApplicationStatus(status)) {
    return 2
  }
  return 1
}

function getFieldDisplayName(field: WorkerFieldState) {
  return field.label || field.question_text || field.canonical_label || field.field_id
}

function formatConfidence(value: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function formatArtifactFileName(path: string) {
  const normalized = path.trim()
  if (!normalized) {
    return 'artifact'
  }
  const segments = normalized.split(/[\\/]/).filter(Boolean)
  return segments[segments.length - 1] ?? normalized
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
  if (status === 'submit_clicked') {
    return 'Submit clicked'
  }
  if (status === 'submitted') {
    return 'Application sent'
  }
  if (status === 'failed') {
    return 'Failed'
  }
  return status.replace(/_/g, ' ')
}

function getWorkerStatusBadgeClassName(status?: string | null) {
  const tone =
    status === 'submitted'
      ? 'success'
      : status === 'failed'
        ? 'error'
        : status === 'submit_clicked' || status === 'awaiting_answers'
          ? 'warning'
          : null

  return tone ? `count-badge count-badge-${tone}` : 'count-badge'
}

function canAssistField(field: WorkerFieldState) {
  if (field.options.length > 0) {
    return false
  }
  return !['select', 'radio', 'checkbox', 'file'].includes(field.field_type)
}

function normalizeProfileEditor(value: Partial<CandidateProfilePayload>) {
  return {
    ...emptyProfile,
    ...value,
    skills: Array.isArray(value.skills) ? value.skills : [],
    achievements: Array.isArray(value.achievements) ? value.achievements : [],
    experiences: Array.isArray(value.experiences) ? value.experiences : [],
    education: Array.isArray(value.education) ? value.education : [],
    links: value.links ?? {},
  }
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

function getFitScoreCardStyle(score: number): CSSProperties {
  const clampedScore = Math.max(0, Math.min(100, score))
  const hue = Math.round((clampedScore / 100) * 120)
  const intensity = clampedScore / 100

  return {
    '--score-border': `hsla(${hue}, 78%, 56%, ${0.3 + intensity * 0.22})`,
    '--score-bg-top': `hsla(${hue}, 82%, 52%, ${0.18 + intensity * 0.14})`,
    '--score-bg-bottom': `hsla(${hue}, 68%, 20%, ${0.08 + intensity * 0.12})`,
    '--score-shadow': `0 16px 28px hsla(${hue}, 88%, 40%, ${0.1 + intensity * 0.18})`,
    '--score-value-color': `hsl(${hue}, 92%, ${68 - intensity * 6}%)`,
    '--score-label-color': `hsla(${hue}, 68%, 84%, 0.88)`,
    '--score-band-color': `hsla(${hue}, 76%, 74%, 0.92)`,
  } as CSSProperties
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
