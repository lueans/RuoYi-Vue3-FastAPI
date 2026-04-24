import MindMap from '@mind-map'
import Drag from '@mind-map/src/plugins/Drag.js'
import Select from '@mind-map/src/plugins/Select.js'
import KeyboardNavigation from '@mind-map/src/plugins/KeyboardNavigation.js'
import MiniMap from '@mind-map/src/plugins/MiniMap.js'
import Export from '@mind-map/src/plugins/Export.js'
import ExportPDF from '@mind-map/src/plugins/ExportPDF.js'
import ExportXMind from '@mind-map/src/plugins/ExportXMind.js'
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
import Formula from '@mind-map/src/plugins/Formula.js'
import NodeBase64ImageStorage from '@mind-map/src/plugins/NodeBase64ImageStorage.js'
import RichText from '@mind-map/src/plugins/RichText.js'

const presets = {
  minimal: [Drag, Select, KeyboardNavigation],
  standard: [
    Drag, Select, KeyboardNavigation,
    MiniMap, Export, NodeImgAdjust, TouchEvent,
    ScrollbarPlugin, Search, AssociativeLine
  ],
  full: [
    Drag, Select, KeyboardNavigation,
    MiniMap, Export, ExportPDF, ExportXMind,
    NodeImgAdjust, TouchEvent,
    Search, AssociativeLine,
    Painter, RainbowLines, Demonstrate,
    OuterFrame, MindMapLayoutPro, Watermark,
    Formula, NodeBase64ImageStorage
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

export { presets, RichText, ScrollbarPlugin }
export default registerPlugins
