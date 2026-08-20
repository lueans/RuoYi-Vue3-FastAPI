import MindMap from '@mind-map'
import Drag from '@mind-map/src/plugins/Drag.js'
import Select from '@mind-map/src/plugins/Select.js'
import KeyboardNavigation from '@mind-map/src/plugins/KeyboardNavigation.js'
import MiniMap from '@mind-map/src/plugins/MiniMap.js'
import Export from '@mind-map/src/plugins/Export.js'
import NodeImgAdjust from '@mind-map/src/plugins/NodeImgAdjust.js'
import TouchEvent from '@mind-map/src/plugins/TouchEvent.js'
import ScrollbarPlugin from '@mind-map/src/plugins/Scrollbar.js'
import Search from '@mind-map/src/plugins/Search.js'
import AssociativeLine from '@mind-map/src/plugins/AssociativeLine'
import Painter from '@mind-map/src/plugins/Painter.js'
import RainbowLines from '@mind-map/src/plugins/RainbowLines.js'
import Demonstrate from '@mind-map/src/plugins/Demonstrate.js'
import OuterFrame from '@mind-map/src/plugins/OuterFrame.js'
import MindMapLayoutPro from '@mind-map/src/plugins/MindMapLayoutPro.js'
import Watermark from '@mind-map/src/plugins/Watermark.js'
import NodeBase64ImageStorage from '@mind-map/src/plugins/NodeBase64ImageStorage.js'
import RichText from '@mind-map/src/plugins/RichText.js'
import { MINDMAP_PREVIEW_FEATURES } from '@/utils/mindmap-preview'
import { ensureMindmapFeaturePlugin } from '@/utils/mindmap-plugin-loader'

const presets = {
  minimal: [Drag, Select, KeyboardNavigation],
  standard: [
    Drag, Select, KeyboardNavigation,
    MiniMap, Export, NodeImgAdjust, TouchEvent,
    ScrollbarPlugin, Search, AssociativeLine
  ],
  full: [
    Drag, Select, KeyboardNavigation,
    MiniMap, Export,
    NodeImgAdjust, TouchEvent,
    Search, AssociativeLine,
    Painter, RainbowLines, Demonstrate,
    OuterFrame, MindMapLayoutPro, Watermark,
    NodeBase64ImageStorage
  ]
}

export function registerPlugins(preset = 'standard', extraPlugins = []) {
  const plugins = presets[preset] || presets.standard
  const all = [...plugins, ...extraPlugins]
  all.forEach(plugin => {
    if (MindMap.hasPlugin(plugin) === -1) {
      MindMap.usePlugin(plugin)
    }
  })
}

const exportPluginLoaders = {
  pdf: () => import('@mind-map/src/plugins/ExportPDF.js'),
  xmind: () => import('@mind-map/src/plugins/ExportXMind.js'),
}

const exportPluginPromises = new Map()

/**
 * 公式引擎包含 KaTeX，只在文档实际包含公式或用户打开公式工具时加载。
 * 无实例时先注册到后续 MindMap 构造流程；有实例时同时初始化当前实例。
 */
export async function ensureFormulaPlugin(mindMap = null) {
  return ensureMindmapFeaturePlugin(MINDMAP_PREVIEW_FEATURES.formula, mindMap)
}

/**
 * 按导出格式为当前实例加载重型插件。Promise 会跨组件复用，避免连续点击
 * 导出时重复下载模块；addPlugin 同时负责注册全局插件并初始化当前实例。
 */
export async function ensureExportPlugins(mindMap, type) {
  if (!mindMap) throw new Error('脑图实例尚未就绪')
  const loader = exportPluginLoaders[type]
  if (!loader) return
  let pluginPromise = exportPluginPromises.get(type)
  if (!pluginPromise) {
    pluginPromise = loader()
      .then(module => module.default)
      .catch(error => {
        exportPluginPromises.delete(type)
        throw error
      })
    exportPluginPromises.set(type, pluginPromise)
  }
  const plugin = await pluginPromise
  if (!mindMap[plugin.instanceName]) mindMap.addPlugin(plugin)
}

export { presets, RichText, ScrollbarPlugin }
export default registerPlugins
