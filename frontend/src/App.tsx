import { useState, useEffect } from 'react'
import type { View } from './types'
import Sidebar from './components/Sidebar/Sidebar'
import TopBar from './components/TopBar/TopBar'
import ActivityView from './components/Activity/ActivityView'
import JobListView from './components/Jobs/JobListView'
import SettingsModal from './components/Settings/SettingsModal'
import SettingsInline from './components/Settings/SettingsInline'
import { useJobsStore } from './store/jobsStore'
import { getJobCounts } from './api'

export default function App() {
  const [view, setView] = useState<View>('activity')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const setCounts = useJobsStore((s) => s.setCounts)

  // Load initial counts
  useEffect(() => {
    getJobCounts().then(setCounts).catch(console.error)
  }, [setCounts])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <TopBar onOpenSettings={() => setSettingsOpen(true)} />

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar view={view} onChangeView={setView} />

        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
          {view === 'activity' && <ActivityView />}
          {view === 'ready' && (
            <JobListView
              status="ready"
              title="Ready to Apply"
              emptyMessage="No jobs ready yet. Start the agent to scrape Upwork."
            />
          )}
          {view === 'applying' && (
            <JobListView
              status="applying"
              title="In Progress"
              emptyMessage="No applications in progress."
            />
          )}
          {view === 'applied' && (
            <JobListView
              status="applied"
              title="Applied / Past"
              emptyMessage="No applied jobs yet."
            />
          )}
          {view === 'pending' && (
            <JobListView
              status="seen"
              title="Pending (Cover Letter Failed)"
              emptyMessage="No pending jobs. All jobs have been processed successfully."
            />
          )}
          {view === 'settings' && (
            <div style={{ padding: 40, maxWidth: 640, margin: '0 auto', width: '100%', overflowY: 'auto' }}>
              <h2 style={{ margin: '0 0 20px', fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
                Settings
              </h2>
              <SettingsInline />
            </div>
          )}
        </main>
      </div>

      {settingsOpen && (
        <SettingsModal onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  )
}
