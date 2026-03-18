export type JobStatus = 'seen' | 'ready' | 'applying' | 'applied' | 'skipped'

export interface Job {
  id: string
  title: string
  client_name: string
  budget: string
  job_type: string
  experience: string
  description: string
  skills: string[]
  job_url: string
  status: JobStatus
  cover_letter_text: string
  cover_letter_pdf: string
  connects_required: number
  found_at: string
  applied_at: string | null
  updated_at: string
}

export interface JobCounts {
  seen: number
  ready: number
  applying: number
  applied: number
  skipped: number
  past: number
}

export interface Settings {
  model: string
  keywords: string[]
  budget_min: string
  budget_max: string
  job_type: string
  experience: string
  max_jobs_per_run: string
  chrome_profile: string
  freelancer_name: string
  freelancer_skills: string[]
  freelancer_bio: string
  resume_path: string
  portfolio_path: string
  openai_api_key?: string
  dashscope_api_key?: string
  auto_run_hours?: string
}

export interface LogEntry {
  id: string
  level: 'info' | 'warn' | 'error'
  message: string
  timestamp: string
}

export type View = 'activity' | 'ready' | 'applying' | 'applied' | 'pending' | 'settings'

export interface SSEEvent {
  type: string
  [key: string]: unknown
}
