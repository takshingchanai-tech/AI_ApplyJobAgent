import { create } from 'zustand'
import type { Job, JobCounts } from '../types'

interface JobsStore {
  jobs: Job[]
  counts: JobCounts
  setJobs: (jobs: Job[]) => void
  upsertJob: (job: Job) => void
  setCounts: (counts: JobCounts) => void
  removeJob: (id: string) => void
}

const defaultCounts: JobCounts = { seen: 0, ready: 0, applying: 0, applied: 0, skipped: 0, past: 0 }

export const useJobsStore = create<JobsStore>((set) => ({
  jobs: [],
  counts: defaultCounts,

  setJobs: (jobs) => set({ jobs }),

  upsertJob: (job) =>
    set((state) => {
      const idx = state.jobs.findIndex((j) => j.id === job.id)
      if (idx >= 0) {
        const updated = [...state.jobs]
        updated[idx] = job
        return { jobs: updated }
      }
      return { jobs: [job, ...state.jobs] }
    }),

  setCounts: (counts) => set({ counts }),

  removeJob: (id) =>
    set((state) => ({ jobs: state.jobs.filter((j) => j.id !== id) })),
}))
