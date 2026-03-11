import type {
  ApplicationDraftResponse,
  ApplicationDraftAssistResponse,
  BulkDeleteResponse,
  CandidateProfilePayload,
  CandidateProfileResponse,
  DashboardResponse,
  DeleteResponse,
  JobLeadResponse,
  ScreeningAnswerPayload,
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
      fixture_html: payload.fixture_html,
      answer_overrides: payload.answer_overrides ?? [],
      cover_note: payload.cover_note,
      screening_answers: payload.screening_answers,
    }),
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
