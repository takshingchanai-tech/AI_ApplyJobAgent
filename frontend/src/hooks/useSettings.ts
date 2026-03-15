import { useCallback, useEffect } from 'react'
import { useSettingsStore } from '../store/settingsStore'
import { getSettings, putSettings } from '../api'
import type { Settings } from '../types'

export function useSettings() {
  const store = useSettingsStore()

  useEffect(() => {
    if (!store.settings) {
      getSettings().then(store.setSettings).catch(console.error)
    }
  }, [store])

  const save = useCallback(
    async (updates: Partial<Settings>) => {
      const result = await putSettings(updates)
      store.setSettings(result)
      return result
    },
    [store]
  )

  return {
    settings: store.settings,
    save,
    reload: () => getSettings().then(store.setSettings),
  }
}
