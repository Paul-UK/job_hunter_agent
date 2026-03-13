import type {
  ApplicationDraftResponse,
  ApplicationDraftAssistResponse,
  BackgroundTaskResponse,
  BulkDeleteResponse,
  CandidateProfilePayload,
  CandidateProfileResponse,
  DashboardResponse,
  DeleteResponse,
  JobLeadResponse,
  SavedSearchMatchResponse,
  SavedSearchResponse,
  SearchPreferencesPayload,
  ScreeningAnswerPayload,
  WebJobDiscoveryResponse,
  WorkerAnswerOverride,
  WorkerRunResponse,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export function buildApiUrl(path: string) {
  return `${API_BASE}${path}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildApiUrl(path), {
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? ''

    if (contentType.includes('application/json')) {
      const payload = (await response.json().catch(() => null)) as
        | { detail?: string }
        | null
      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        throw new Error(payload.detail)
      }
    }

    const detail = await response.text()
    throw new Error(detail || `Request failed with status ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function getDashboard() {
  return request<DashboardResponse>('/api/dashboard')
}

export async function uploadCv(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<CandidateProfileResponse>('/api/profile/cv', {
    method: 'POST',
    body: form,
  })
}

export async function uploadLinkedinText(text: string) {
  const form = new FormData()
  form.append('text', text)
  return request<CandidateProfileResponse>('/api/profile/linkedin', {
    method: 'POST',
    body: form,
  })
}

export async function uploadLinkedinFile(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<CandidateProfileResponse>('/api/profile/linkedin', {
    method: 'POST',
    body: form,
  })
}

export function updateProfile(payload: CandidateProfilePayload) {
  return request<CandidateProfileResponse>('/api/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteProfileSource(sourceId: number) {
  return request<DeleteResponse>(`/api/profile/sources/${sourceId}`, {
    method: 'DELETE',
  })
}

export function discoverGreenhouse(identifiers: string[]) {
  return request<JobLeadResponse[]>('/api/jobs/discover/greenhouse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identifiers, include_questions: true }),
  })
}

export function discoverLever(identifiers: string[]) {
  return request<JobLeadResponse[]>('/api/jobs/discover/lever', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identifiers }),
  })
}

export function discoverAshby(identifiers: string[]) {
  return request<JobLeadResponse[]>('/api/jobs/discover/ashby', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ identifiers }),
  })
}

export function discoverWebJobs(search_preferences: SearchPreferencesPayload) {
  return request<WebJobDiscoveryResponse>('/api/jobs/discover/web', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ search_preferences }),
  })
}

export function createSavedSearch(payload: {
  name: string
  search_preferences: SearchPreferencesPayload
  enabled?: boolean
  cadence_minutes?: number
}) {
  return request<SavedSearchResponse>('/api/searches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: payload.name,
      search_preferences: payload.search_preferences,
      enabled: payload.enabled ?? true,
      cadence_minutes: payload.cadence_minutes ?? 1440,
    }),
  })
}

export function updateSavedSearch(
  searchId: number,
  payload: {
    name?: string
    search_preferences?: SearchPreferencesPayload
    enabled?: boolean
    cadence_minutes?: number
  },
) {
  return request<SavedSearchResponse>(`/api/searches/${searchId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteSavedSearch(searchId: number) {
  return request<{ deleted_id: number }>(`/api/searches/${searchId}`, {
    method: 'DELETE',
  })
}

export function runSavedSearch(searchId: number) {
  return request<BackgroundTaskResponse>(`/api/searches/${searchId}/run`, {
    method: 'POST',
  })
}

export function saveSearchFeedback(
  searchId: number,
  jobId: number,
  payload: { signal: 'neutral' | 'shortlisted' | 'dismissed' | 'drafted' | 'applied'; note?: string },
) {
  return request<SavedSearchMatchResponse>(`/api/searches/${searchId}/matches/${jobId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function captureLinkedinLead(payload: {
  company: string
  title: string
  url?: string
  location?: string
  description?: string
  notes?: string
}) {
  return request<JobLeadResponse>('/api/jobs/discover/linkedin', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function createDraft(jobId: number) {
  return request<ApplicationDraftResponse>(`/api/jobs/${jobId}/draft`, {
    method: 'POST',
  })
}

export function deleteJobLead(jobId: number) {
  return request<DeleteResponse>(`/api/jobs/${jobId}`, {
    method: 'DELETE',
  })
}

export function updateJobCrm(
  jobId: number,
  payload: {
    crm_stage?: 'new' | 'shortlisted' | 'drafted' | 'applied' | 'interviewing' | 'offer' | 'rejected' | 'archived'
    crm_notes?: string | null
    follow_up_at?: string | null
    last_contacted_at?: string | null
    is_active?: boolean
  },
) {
  return request<JobLeadResponse>(`/api/jobs/${jobId}/crm`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function bulkDeleteJobLeads(jobIds: number[]) {
  return request<BulkDeleteResponse>('/api/jobs/bulk-delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_ids: jobIds }),
  })
}

export function assistApplicationDraft(
  applicationId: number,
  payload: {
    target: 'cover_note' | 'question_answer'
    question?: string
    current_text?: string
    persist?: boolean
  },
) {
  return request<ApplicationDraftAssistResponse>(`/api/applications/${applicationId}/assist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target: payload.target,
      question: payload.question,
      current_text: payload.current_text,
      persist: payload.persist ?? true,
    }),
  })
}

export function runWorker(
  applicationId: number,
  payload: {
    dry_run?: boolean
    confirm_submit?: boolean
    retry_anyway?: boolean
    fixture_html?: string
    answer_overrides?: WorkerAnswerOverride[]
    cover_note?: string
    screening_answers?: ScreeningAnswerPayload[]
  } = {},
) {
  return request<WorkerRunResponse>(`/api/applications/${applicationId}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dry_run: payload.dry_run ?? true,
      confirm_submit: payload.confirm_submit ?? false,
      retry_anyway: payload.retry_anyway ?? false,
      fixture_html: payload.fixture_html,
      answer_overrides: payload.answer_overrides ?? [],
      cover_note: payload.cover_note,
      screening_answers: payload.screening_answers,
    }),
  })
}

export function queueWorkerRun(
  applicationId: number,
  payload: {
    dry_run?: boolean
    confirm_submit?: boolean
    retry_anyway?: boolean
    fixture_html?: string
    answer_overrides?: WorkerAnswerOverride[]
    cover_note?: string
    screening_answers?: ScreeningAnswerPayload[]
  } = {},
) {
  return request<BackgroundTaskResponse>(`/api/applications/${applicationId}/queue-run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dry_run: payload.dry_run ?? true,
      confirm_submit: payload.confirm_submit ?? false,
      retry_anyway: payload.retry_anyway ?? false,
      fixture_html: payload.fixture_html,
      answer_overrides: payload.answer_overrides ?? [],
      cover_note: payload.cover_note,
      screening_answers: payload.screening_answers,
    }),
  })
}

export function processBackgroundTasks(limit = 1) {
  return request<{ processed: number }>(`/api/tasks/process?limit=${limit}`, {
    method: 'POST',
  })
}

export function deleteApplicationDraft(applicationId: number) {
  return request<DeleteResponse>(`/api/applications/${applicationId}`, {
    method: 'DELETE',
  })
}

export function deleteWorkerRun(runId: number) {
  return request<DeleteResponse>(`/api/applications/runs/${runId}`, {
    method: 'DELETE',
  })
}
