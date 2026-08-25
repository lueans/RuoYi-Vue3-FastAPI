import MindMap from '@mind-map'
import {
  MINDMAP_PREVIEW_FEATURES,
  detectMindmapDocumentFeatures,
} from '@/utils/mindmap-preview'

const featurePluginLoaders = Object.freeze({
  [MINDMAP_PREVIEW_FEATURES.associativeLine]: () => import('@mind-map/src/plugins/AssociativeLine'),
  [MINDMAP_PREVIEW_FEATURES.outerFrame]: () => import('@mind-map/src/plugins/OuterFrame.js'),
  [MINDMAP_PREVIEW_FEATURES.formula]: () => import('@mind-map/src/plugins/Formula.js'),
  [MINDMAP_PREVIEW_FEATURES.mindMapLayoutPro]: () => import('@mind-map/src/plugins/MindMapLayoutPro.js'),
  [MINDMAP_PREVIEW_FEATURES.richText]: () => import('@mind-map/src/plugins/RichTextViewer.js'),
  [MINDMAP_PREVIEW_FEATURES.watermark]: () => import('@mind-map/src/plugins/Watermark.js'),
})

const featurePluginInstanceNames = Object.freeze({
  [MINDMAP_PREVIEW_FEATURES.associativeLine]: 'associativeLine',
  [MINDMAP_PREVIEW_FEATURES.outerFrame]: 'outerFrame',
  [MINDMAP_PREVIEW_FEATURES.formula]: 'formula',
  [MINDMAP_PREVIEW_FEATURES.mindMapLayoutPro]: 'mindMapLayoutPro',
  [MINDMAP_PREVIEW_FEATURES.richText]: 'richTextViewer',
  [MINDMAP_PREVIEW_FEATURES.watermark]: 'watermark',
})

const featurePluginPromises = new Map()

/**
 * 加载并注册单项文档能力。模块 Promise 跨编辑器和预览实例复用；失败时
 * 清除缓存，使用户的下一次重试能够真正重新请求模块。
 */
export async function ensureMindmapFeaturePlugin(feature, mindMap = null) {
  const loader = featurePluginLoaders[feature]
  if (!loader) throw new Error(`不支持的脑图文档能力：${feature}`)

  // 编辑器为保证 Yjs 增量渲染会常驻部分插件；优先复用已注册类，避免同一
  // 能力再经过动态模块入口。公开预览没有这些常驻项，仍会走真正的按需加载。
  const instanceName = featurePluginInstanceNames[feature]
  const registeredPlugin = MindMap.pluginList?.find(plugin => plugin?.instanceName === instanceName)
  if (registeredPlugin) {
    if (mindMap && !mindMap[instanceName]) mindMap.addPlugin(registeredPlugin)
    return registeredPlugin
  }

  let pluginPromise = featurePluginPromises.get(feature)
  if (!pluginPromise) {
    pluginPromise = loader()
      .then(module => module.default)
      .catch(error => {
        featurePluginPromises.delete(feature)
        throw error
      })
    featurePluginPromises.set(feature, pluginPromise)
  }

  const plugin = await pluginPromise
  if (MindMap.hasPlugin(plugin) === -1) MindMap.usePlugin(plugin)
  if (mindMap && !mindMap[plugin.instanceName]) mindMap.addPlugin(plugin)
  return plugin
}

/**
 * 在文档进入画布前安装它实际需要的插件。该入口同时服务编辑器首次加载、
 * 运行期数据替换、公开预览和模板预览，避免各入口维护不同的能力规则。
 */
export async function ensureMindmapDocumentPlugins(document, mindMap = null) {
  const features = detectMindmapDocumentFeatures(document)
  await Promise.all(features.map(feature => ensureMindmapFeaturePlugin(feature, mindMap)))
  return features
}

export default ensureMindmapDocumentPlugins
