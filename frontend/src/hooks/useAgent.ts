import { useEffect, useRef, useCallback } from 'react'
import { useAgentStore } from '../store/agentStore'
import { useJobsStore } from '../store/jobsStore'
import { startAgent, stopAgent, getJobCounts, getJob } from '../api'
import type { SSEEvent } from '../types'

export function useAgent() {
  const agentStore = useAgentStore()
  const jobsStore = useJobsStore()
  const eventSourceRef = useRef<EventSource | null>(null)

  const connectSSE = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const es = new EventSource('/agent/stream')
    eventSourceRef.current = es

    es.onmessage = (e) => {
      try {
        const event: SSEEvent = JSON.parse(e.data)
        handleEvent(event)
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      // EventSource auto-reconnects — just log
      agentStore.appendLog({ level: 'warn', message: 'SSE connection lost, reconnecting...' })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleEvent(event: SSEEvent) {
    switch (event.type) {
      case 'ping':
        break

      case 'agent_started':
        agentStore.setRunning(true, event.run_id as string)
        agentStore.appendLog({ level: 'info', message: `Agent started (run ${event.run_id})` })
        break

      case 'agent_stopped':
        agentStore.setRunning(false)
        agentStore.appendLog({ level: 'info', message: `Agent stopped (${event.reason})` })
        // Refresh counts
        getJobCounts().then(jobsStore.setCounts).catch(() => {})
        break

      case 'log':
        agentStore.appendLog({
          level: (event.level as 'info' | 'warn' | 'error') || 'info',
          message: event.message as string,
        })
        break

      case 'job_found':
        agentStore.appendLog({
          level: 'info',
          message: `Found: ${event.title} (${event.budget || 'no budget'})`,
        })
        break

      case 'job_skipped':
        agentStore.appendLog({
          level: 'info',
          message: `Skipped job ${event.job_id}: ${event.reason}`,
        })
        break

      case 'generating_cover_letter':
        agentStore.appendLog({
          level: 'info',
          message: `Generating cover letter for: ${event.title}`,
        })
        break

      case 'job_ready':
        agentStore.appendLog({
          level: 'info',
          message: `Ready to apply: ${event.title}`,
        })
        // Fetch full job and add to store
        getJob(event.job_id as string)
          .then((job) => jobsStore.upsertJob(job))
          .catch(() => {})
        break

      case 'counts_updated':
        if (event.counts) {
          jobsStore.setCounts(event.counts as any)
        }
        break

      case 'error':
        agentStore.appendLog({
          level: 'error',
          message: event.message as string,
        })
        break

      case 'done':
        agentStore.appendLog({
          level: 'info',
          message: `Done. Jobs found: ${event.jobs_found}, Ready: ${event.jobs_ready}`,
        })
        break
    }
  }

  useEffect(() => {
    connectSSE()
    return () => {
      eventSourceRef.current?.close()
    }
  }, [connectSSE])

  const start = useCallback(async () => {
    try {
      agentStore.clearLog()
      await startAgent()
    } catch (err: any) {
      agentStore.appendLog({ level: 'error', message: `Failed to start: ${err.message}` })
    }
  }, [agentStore])

  const stop = useCallback(async () => {
    try {
      await stopAgent()
    } catch (err: any) {
      agentStore.appendLog({ level: 'error', message: `Failed to stop: ${err.message}` })
    }
  }, [agentStore])

  return {
    running: agentStore.running,
    log: agentStore.log,
    start,
    stop,
  }
}
