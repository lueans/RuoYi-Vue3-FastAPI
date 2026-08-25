import 'quill/dist/quill.snow.css'
import { RICH_TEXT_NODE_CSS } from './RichTextStyle'

const STYLE_KEY = 'richTextViewer'

// 只读和协作准备阶段只需要富文本节点的展示样式。完整 RichText 插件
// 会在实例化时把整棵当前树转换为富文本并清空历史，不能作为展示依赖加载。
class RichTextViewer {
  constructor({ mindMap }) {
    this.mindMap = mindMap
    this.mindMap.appendCss(STYLE_KEY, RICH_TEXT_NODE_CSS)
  }

  removeStyle() {
    this.mindMap.removeAppendCss(STYLE_KEY)
  }

  beforePluginRemove() {
    this.removeStyle()
  }

  beforePluginDestroy() {
    this.removeStyle()
  }
}

RichTextViewer.instanceName = 'richTextViewer'

export default RichTextViewer
