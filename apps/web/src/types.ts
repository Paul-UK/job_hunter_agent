export type ProfileSourceType = 'cv' | 'linkedin'

export interface ExperienceItem {
  company: string
  title?: string | null
  duration?: string | null
  highlights: string[]
}

export interface EducationItem {
  institution: string
  degree?: string | null
  details?: string | null
}

export interface CandidateProfilePayload {
  full_name?: string | null
  headline?: string | null
  email?: string | null
  phone?: string | null
  location?: string | null
  summary?: string | null
  skills: string[]
  achievements: string[]
  experiences: ExperienceItem[]
  education: EducationItem[]
  links: Record<string, string>
}

export interface CandidateProfileResponse {
  id: number
  full_name?: string | null
  headline?: string | null
  email?: string | null
  phone?: string | null
  location?: string | null
  source_of_truth: string
  merged_profile: CandidateProfilePayload
  field_sources: Record<string, string>
}

export interface ProfileSourcePayload {
  id?: number | null
  source_type: ProfileSourceType
  source_label: string
  confidence: Record<string, number>
  payload: CandidateProfilePayload
}

export interface JobLeadResponse {
  id: number
  source: string
  company: string
  title: string
  location?: string | null
  employment_type?: string | null
  url: string
  description: string
  score?: number | null
  status: string
  requirements: string[]
  metadata_json: Record<string, unknown>
  score_details: {
    summary?: string
    matched_signals?: string[]
    matched_skills?: string[]
    missing_signals?: string[]
  }
  research: {
    website_summary?: string
    github_org?: string
    github_summary?: string
    top_languages?: string[]
  }
}

export interface ScreeningAnswerPayload {
  question: string
  answer: string
}

export interface ApplicationDraftResponse {
  id: number
  profile_id: number
  job_lead_id: number
  tailored_summary: string
  cover_note: string
  resume_bullets: string[]
  screening_answers: ScreeningAnswerPayload[]
  status: string
}

export interface ApplicationDraftAssistResponse {
  text: string
  confidence: number
  reasoning: string
  updated_draft?: ApplicationDraftResponse | null
}

export interface DeleteResponse {
  entity: 'job_lead' | 'application_draft' | 'worker_run' | 'profile_source'
  deleted_id: number
  deleted_counts: Record<string, number>
}

export interface BulkDeleteResponse {
  entity: 'job_leads'
  deleted_ids: number[]
  deleted_counts: Record<string, number>
}

export interface WorkerFieldOption {
  label: string
  value: string
  selector?: string | null
}

export interface WorkerFieldState {
  field_id: string
  label: string
  question_text: string
  selector: string
  field_type: string
  input_type?: string | null
  html_name?: string | null
  html_id?: string | null
  placeholder?: string | null
  required: boolean
  options: WorkerFieldOption[]
  section?: string | null
  canonical_key?: string | null
  canonical_label?: string | null
  classification_confidence: number
  classification_source?: string | null
  classification_reasoning?: string | null
  answer_value?: string | null
  answer_source?: string | null
  answer_confidence: number
  requires_review: boolean
  review_reason?: string | null
}

export interface WorkerPreviewSummary {
  total_fields: number
  autofill_ready_count: number
  required_count: number
  review_required_count: number
  unresolved_required_count: number
  llm_suggestions_count: number
}

export interface WorkerAnswerOverride {
  field_id: string
  value: string
}

export interface WorkerRunResponse {
  id: number
  application_draft_id?: number | null
  platform: string
  target_url: string
  dry_run: boolean
  status: string
  actions: Array<{
    field: string
    selector: string
    value: string
    field_id?: string | null
    mode?: string
  }>
  logs: string[]
  screenshot_path?: string | null
  fields: WorkerFieldState[]
  review_items: WorkerFieldState[]
  preview_summary: WorkerPreviewSummary
  profile_snapshot: Record<string, unknown>
  job_snapshot: Record<string, unknown>
  draft_snapshot: Record<string, unknown>
  created_at?: string | null
}

export interface DashboardResponse {
  profile: CandidateProfileResponse | null
  profile_sources: ProfileSourcePayload[]
  jobs: JobLeadResponse[]
  applications: ApplicationDraftResponse[]
  worker_runs: WorkerRunResponse[]
}
