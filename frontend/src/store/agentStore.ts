import { create } from 'zustand'
import type { LogEntry } from '../types'

interface AgentStore {
  running: boolean
  runId: string | null
  log: LogEntry[]
  setRunning: (running: boolean, runId?: string | null) => void
  appendLog: (entry: Omit<LogEntry, 'id' | 'timestamp'>) => void
  clearLog: () => void
}

export const useAgentStore = create<AgentStore>((set) => ({
  running: false,
  runId: null,
  log: [],

  setRunning: (running, runId = null) => set({ running, runId }),

  appendLog: (entry) =>
    set((state) => ({
      log: [
        ...state.log,
        {
          id: `log_${Date.now()}_${Math.random()}`,
          timestamp: new Date().toISOString(),
          ...entry,
        },
      ].slice(-200), // keep last 200 entries
    })),

  clearLog: () => set({ log: [] }),
}))
