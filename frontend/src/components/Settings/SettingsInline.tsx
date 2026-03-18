/**
 * Inline settings form (for the Settings nav view, no modal overlay).
 * Reuses the same form logic as SettingsModal but without the backdrop.
 */
import { useState, useEffect } from 'react'
import { useSettings } from '../../hooks/useSettings'
import { uploadResume, uploadPortfolio } from '../../api'
import type { Settings } from '../../types'

export default function SettingsInline() {
  const { settings, save } = useSettings()
  const [form, setForm] = useState<Partial<Settings>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [keywordsText, setKeywordsText] = useState('')
  const [skillsText, setSkillsText] = useState('')

  useEffect(() => {
    if (settings) {
      setForm({ ...settings })
      setKeywordsText(
        Array.isArray(settings.keywords) ? settings.keywords.join(', ') : settings.keywords || ''
      )
      setSkillsText(
        Array.isArray(settings.freelancer_skills)
          ? settings.freelancer_skills.join(', ')
          : settings.freelancer_skills || ''
      )
    }
  }, [settings])

  function set(key: keyof Settings, value: unknown) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const updates: Partial<Settings> = {
        ...form,
        keywords: keywordsText.split(',').map((k) => k.trim()).filter(Boolean),
        freelancer_skills: skillsText.split(',').map((s) => s.trim()).filter(Boolean),
      }
      await save(updates)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleResumeUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const result = await uploadResume(file)
      set('resume_path', result.path)
    } catch (err: any) {
      setError(`Resume upload failed: ${err.message}`)
    }
  }

  async function handlePortfolioUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const result = await uploadPortfolio(file)
      set('portfolio_path', result.path)
    } catch (err: any) {
      setError(`Portfolio upload failed: ${err.message}`)
    }
  }

  if (!settings) return <div style={{ color: 'var(--text-muted)', padding: 20 }}>Loading settings...</div>

  return (
    <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Section title="AI Model">
        <Label>Model</Label>
        <select value={form.model || 'gpt-4o-mini'} onChange={(e) => set('model', e.target.value)} style={selectStyle}>
          <option value="gpt-4o-mini">GPT-4o Mini (OpenAI)</option>
          <option value="qwen-max">Qwen Max (DashScope)</option>
        </select>
        <Label>OpenAI API Key</Label>
        <input type="password" value={form.openai_api_key || ''} onChange={(e) => set('openai_api_key', e.target.value)} placeholder="sk-..." style={inputStyle} />
        <Label>DashScope API Key (Qwen)</Label>
        <input type="password" value={form.dashscope_api_key || ''} onChange={(e) => set('dashscope_api_key', e.target.value)} placeholder="sk-..." style={inputStyle} />
      </Section>

      <Section title="Search Filters">
        <Label>Keywords (comma-separated)</Label>
        <input value={keywordsText} onChange={(e) => setKeywordsText(e.target.value)} placeholder="python developer, fastapi, automation" style={inputStyle} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div><Label>Budget Min ($)</Label><input value={form.budget_min || ''} onChange={(e) => set('budget_min', e.target.value)} placeholder="0" style={inputStyle} /></div>
          <div><Label>Budget Max ($)</Label><input value={form.budget_max || ''} onChange={(e) => set('budget_max', e.target.value)} placeholder="0 = any" style={inputStyle} /></div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <Label>Job Type</Label>
            <select value={form.job_type || 'any'} onChange={(e) => set('job_type', e.target.value)} style={selectStyle}>
              <option value="any">Any</option><option value="fixed">Fixed</option><option value="hourly">Hourly</option>
            </select>
          </div>
          <div>
            <Label>Experience Level</Label>
            <select value={form.experience || 'any'} onChange={(e) => set('experience', e.target.value)} style={selectStyle}>
              <option value="any">Any</option><option value="entry">Entry Level</option><option value="intermediate">Intermediate</option><option value="expert">Expert</option>
            </select>
          </div>
        </div>
        <Label>Max Jobs Per Run</Label>
        <input type="number" value={form.max_jobs_per_run || '10'} onChange={(e) => set('max_jobs_per_run', e.target.value)} min={1} max={50} style={inputStyle} />
      </Section>

      <Section title="Freelancer Profile">
        <Label>Your Name</Label>
        <input value={form.freelancer_name || ''} onChange={(e) => set('freelancer_name', e.target.value)} placeholder="John Doe" style={inputStyle} />
        <Label>Skills (comma-separated)</Label>
        <input value={skillsText} onChange={(e) => setSkillsText(e.target.value)} placeholder="Python, FastAPI, React" style={inputStyle} />
        <Label>Bio / Summary</Label>
        <textarea value={form.freelancer_bio || ''} onChange={(e) => set('freelancer_bio', e.target.value)} placeholder="Brief professional bio..." rows={4} style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit' }} />
      </Section>

      <Section title="Attachments">
        <Label>Resume PDF</Label>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <input type="file" accept=".pdf" onChange={handleResumeUpload} style={{ fontSize: 13, color: 'var(--text-secondary)' }} />
          {form.resume_path && <span style={{ fontSize: 11, color: '#22c55e' }}>✓ Uploaded</span>}
        </div>
        <Label>Portfolio PDF</Label>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <input type="file" accept=".pdf" onChange={handlePortfolioUpload} style={{ fontSize: 13, color: 'var(--text-secondary)' }} />
          {form.portfolio_path && <span style={{ fontSize: 11, color: '#22c55e' }}>✓ Uploaded</span>}
        </div>
      </Section>

      <Section title="Browser">
        <Label>Chrome Profile Path</Label>
        <input value={form.chrome_profile || ''} onChange={(e) => set('chrome_profile', e.target.value)} placeholder="/Users/you/Library/Application Support/Google/Chrome/Default" style={inputStyle} />
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Leave empty for a fresh browser session.</div>
      </Section>

      <Section title="Auto-Run Schedule">
        <Label>Run Every N Hours (0 = disabled)</Label>
        <input type="number" value={form.auto_run_hours || '0'} onChange={(e) => set('auto_run_hours', e.target.value)} min={0} step={0.5} placeholder="0" style={inputStyle} />
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Set to e.g. 6 to auto-run the agent every 6 hours. Requires the backend to be running.</div>
      </Section>

      {error && <div style={{ color: '#ef4444', fontSize: 13 }}>{error}</div>}

      <button type="submit" disabled={saving} style={primaryBtn}>
        {saving ? 'Saving...' : saved ? '✓ Saved!' : 'Save Settings'}
      </button>
    </form>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10, paddingBottom: 6, borderBottom: '1px solid var(--border)' }}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{children}</div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 500, marginTop: 4 }}>{children}</div>
}

const inputStyle: React.CSSProperties = {
  padding: '8px 10px', fontSize: 13, background: 'var(--bg-surface)',
  border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-primary)',
  width: '100%', boxSizing: 'border-box',
}

const selectStyle: React.CSSProperties = { ...inputStyle, cursor: 'pointer' }

const primaryBtn: React.CSSProperties = {
  padding: '10px 24px', fontSize: 14, background: 'var(--accent)', color: '#fff',
  border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600, alignSelf: 'flex-start',
}
