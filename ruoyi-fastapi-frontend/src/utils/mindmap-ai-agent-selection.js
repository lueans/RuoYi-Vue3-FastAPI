const DEFAULT_AGENT_KEY = 'native_mindmap'

function normalizedAgents(agents) {
  return Array.isArray(agents)
    ? agents.filter(agent => agent && typeof agent.agentKey === 'string' && agent.agentKey)
    : []
}

/**
 * Preserve an explicit Agent choice. A compatible default is selected only
 * when no choice exists yet; task/source changes must never silently replace
 * the Agent the user already picked.
 */
export function resolveMindmapAiAgentSelection({
  agents,
  selectedAgentKey,
  supportsAgent,
  preferredAgentKey = DEFAULT_AGENT_KEY,
} = {}) {
  const candidates = normalizedAgents(agents)
  const currentKey = typeof selectedAgentKey === 'string' ? selectedAgentKey : ''
  const supports = typeof supportsAgent === 'function' ? supportsAgent : () => true
  const selectedAgent = candidates.find(agent => agent.agentKey === currentKey) || null

  if (currentKey) {
    return {
      agentKey: currentKey,
      selectedAgent,
      autoSelected: false,
    }
  }

  const compatible = candidates.filter(agent => agent.status === 'enabled' && supports(agent))
  const preferred = compatible.find(agent => agent.agentKey === preferredAgentKey)
  const fallback = preferred || compatible[0] || null
  return {
    agentKey: fallback?.agentKey || '',
    selectedAgent: fallback,
    autoSelected: Boolean(fallback),
  }
}
