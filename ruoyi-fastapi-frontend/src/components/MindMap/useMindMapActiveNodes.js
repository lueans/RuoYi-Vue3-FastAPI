import bus from './useEventBus'
import { store } from './useStore'
import { resolveMindmapEventNodes } from '@/utils/mindmap-event'

export function useMindMapActiveNodes({
  resolveMindMap = () => store.mindMap,
  onMindMapChange = null,
  syncOnMount = true,
} = {}) {
  const activeNodes = shallowRef([])
  let componentAlive = true

  function replaceActiveNodes(nodes) {
    activeNodes.value = nodes
  }

  function onNodeActive(_node, nodeList, sourceMindMap = null) {
    const currentMindMap = resolveMindMap()
    const nodes = resolveMindmapEventNodes(nodeList, sourceMindMap, currentMindMap)
    if (nodes === null) return false
    replaceActiveNodes(nodes)
    return true
  }

  function syncActiveNodes() {
    const currentMindMap = resolveMindMap()
    if (!currentMindMap) {
      replaceActiveNodes([])
      return false
    }
    return onNodeActive(
      null,
      currentMindMap.renderer?.activeNodeList || [],
      currentMindMap,
    )
  }

  function clearActiveNodes() {
    replaceActiveNodes([])
  }

  watch(resolveMindMap, (mindMap, oldMindMap) => {
    if (mindMap === oldMindMap) return
    clearActiveNodes()
    onMindMapChange?.(mindMap, oldMindMap)
    if (mindMap) {
      nextTick(() => {
        if (componentAlive && resolveMindMap() === mindMap) syncActiveNodes()
      })
    }
  }, { flush: 'sync' })

  onMounted(() => {
    bus.on('node_active', onNodeActive)
    if (syncOnMount) syncActiveNodes()
  })

  onBeforeUnmount(() => {
    componentAlive = false
    bus.off('node_active', onNodeActive)
    clearActiveNodes()
  })

  return {
    activeNodes,
    clearActiveNodes,
    onNodeActive,
    syncActiveNodes,
  }
}
