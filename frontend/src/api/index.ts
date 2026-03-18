import type { Job, JobCounts, Settings } from '../types'

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

// Health
export const getHealth = () => req<{ status: string; agent_running: boolean; counts: JobCounts }>('/health')

// Agent
export const startAgent = () => req<{ status: string; run_id: string }>('/agent/start', { method: 'POST' })
export const stopAgent = () => req<{ status: string }>('/agent/stop', { method: 'POST' })
export const getAgentStatus = () => req<{ running: boolean; run_id: string | null; started_at: string | null }>('/agent/status')

// Jobs
export const listJobs = (status?: string) =>
  req<Job[]>(`/jobs${status ? `?status=${status}` : ''}`)
export const getJobCounts = () => req<JobCounts>('/jobs/counts')
export const getJob = (id: string) => req<Job>(`/jobs/${id}`)
export const patchJob = (id: string, data: Partial<Job>) =>
  req<Job>(`/jobs/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
export const skipJob = (id: string) => fetch(`/jobs/${id}`, { method: 'DELETE' })
export const openForReview = (id: string) =>
  req<{ status: string; job_id: string }>(`/jobs/${id}/open-for-review`, { method: 'POST' })
export const markApplied = (id: string) =>
  req<Job>(`/jobs/${id}/mark-applied`, { method: 'POST' })
export const retryCoverLetter = (id: string) =>
  req<{ status: string; job_id: string }>(`/jobs/${id}/retry-cover-letter`, { method: 'POST' })

// Settings
export const getSettings = () => req<Settings>('/settings')
export const putSettings = (data: Partial<Settings>) =>
  req<Settings>('/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

// Attachments
export const uploadResume = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return req<{ status: string; path: string }>('/attachments/resume', { method: 'POST', body: form })
}
export const uploadPortfolio = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return req<{ status: string; path: string }>('/attachments/portfolio', { method: 'POST', body: form })
}
