import MindMap from '@mind-map'
import TouchEvent from '@mind-map/src/plugins/TouchEvent.js'
import { ensureMindmapDocumentPlugins } from '@/utils/mindmap-plugin-loader'

function registerPlugin(plugin) {
  if (plugin && MindMap.hasPlugin(plugin) === -1) {
    MindMap.usePlugin(plugin)
  }
}

export async function registerPreviewPlugins(document) {
  registerPlugin(TouchEvent)
  return ensureMindmapDocumentPlugins(document)
}

export default registerPreviewPlugins
