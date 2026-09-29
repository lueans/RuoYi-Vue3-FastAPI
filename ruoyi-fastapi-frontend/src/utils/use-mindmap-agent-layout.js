import { onMounted, onScopeDispose } from 'vue'
import { AGENT_PANEL_WIDTH_KEY, createAgentPanelLayout } from './mindmap-agent-layout.js'

// One geometry source for the teleported drawer and the editor's canvas.
// This browser-local visual preference contains no account/document data.
const layout = createAgentPanelLayout({
  viewport: typeof window === 'undefined' ? 1280 : window.innerWidth,
  read: () => window.localStorage.getItem(AGENT_PANEL_WIDTH_KEY),
  write: width => window.localStorage.setItem(AGENT_PANEL_WIDTH_KEY, String(width)),
})

export function useMindmapAgentLayout() {
  const resize = () => layout.setViewport(window.innerWidth)
  onMounted(() => { resize(); window.addEventListener('resize', resize) })
  onScopeDispose(() => window.removeEventListener('resize', resize))
  return layout
}
