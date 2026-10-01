// Adapted from Open Design project-split-layout.ts. Preferred width and
// responsive/rendered width are separate; resizing never edits a document.
import { computed, readonly, ref } from 'vue'

export const DEFAULT_AGENT_PANEL_WIDTH = 376
export const AGENT_PANEL_WIDTH_KEY = 'mindmap.agent-panel-width.v2'
const MIN_WIDTH = 360
const MAX_WIDTH = 720

export function normalizeAgentPanelWidth(value) {
  if (!['number', 'string'].includes(typeof value) || String(value).trim() === '') return DEFAULT_AGENT_PANEL_WIDTH
  const width = Number(value)
  return Number.isFinite(width) ? Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, Math.round(width))) : DEFAULT_AGENT_PANEL_WIDTH
}

export function agentPanelBounds(viewport) {
  const available = Number.isFinite(viewport) && viewport > 0 ? Math.floor(viewport) : 1280
  if (available <= 760) return { desktop: false, min: available, max: available }
  // Two 44px rails, canvas gaps and a 400px canvas when space permits.
  return { desktop: true, min: MIN_WIDTH, max: Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, available - 104 - 400)) }
}

export function agentPanelKeyboardWidth(event, width, bounds) {
  if (!bounds.desktop || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return null
  const step = event.shiftKey ? 40 : 10
  const next = ({ ArrowLeft: width - step, ArrowRight: width + step, Home: bounds.min, End: bounds.max })[event.key]
  return next === undefined ? null : Math.min(bounds.max, Math.max(bounds.min, next))
}

export function createAgentPanelLayout({ read = () => null, write = () => {}, viewport = 1280 } = {}) {
  let saved
  try { saved = read() } catch {}
  const preferred = ref(normalizeAgentPanelWidth(saved))
  const viewportWidth = ref(viewport)
  const transient = ref(null)
  const bounds = computed(() => agentPanelBounds(viewportWidth.value))
  const clamp = value => Math.min(bounds.value.max, Math.max(bounds.value.min, normalizeAgentPanelWidth(value)))
  const width = computed(() => clamp(transient.value ?? preferred.value))
  function cancel() { transient.value = null }
  function commit(value) {
    if (!bounds.value.desktop) return cancel()
    preferred.value = clamp(value)
    cancel()
    try { write(preferred.value) } catch {}
  }
  return {
    width: readonly(width), bounds: readonly(bounds), resizing: computed(() => transient.value !== null),
    preview(value) { if (bounds.value.desktop) transient.value = clamp(value) },
    commit, cancel,
    reset() {
      preferred.value = DEFAULT_AGENT_PANEL_WIDTH
      cancel()
      try { write(preferred.value) } catch {}
    },
    setViewport(value) {
      if (!Number.isFinite(value) || value <= 0 || value === viewportWidth.value) return
      cancel()
      viewportWidth.value = value
    },
  }
}
