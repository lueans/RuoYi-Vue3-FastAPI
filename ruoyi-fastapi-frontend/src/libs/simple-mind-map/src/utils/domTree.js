import { walkNodeForest } from './nodeForest.js'

const ELEMENT_NODE = 1
const TEXT_NODE = 3

const getChildSnapshot = node => {
  try {
    return node?.childNodes ? Array.from(node.childNodes) : []
  } catch {
    return []
  }
}

// DOM 的 childNodes 是实时集合，变更期间必须先快照当前层。根容器本身
// 不参与回调，保持原工具只处理后代节点的语义。
export const walkDomDescendants = (
  root,
  { onElement, onText } = {}
) => walkNodeForest(
  getChildSnapshot(root),
  (node, frame) => {
    if (node.nodeType === ELEMENT_NODE) {
      return onElement?.(node, frame)
    }
    if (node.nodeType === TEXT_NODE) {
      onText?.(node, frame)
    }
    return false
  },
  node => node.nodeType === ELEMENT_NODE ? getChildSnapshot(node) : []
)

export const applyStyleToDomTags = (root, tags, cssText) => {
  const normalizedTags = new Set(
    (Array.isArray(tags) ? tags : [tags])
      .map(tag => String(tag || '').trim().toLowerCase())
      .filter(Boolean)
  )
  walkDomDescendants(root, {
    onElement(element) {
      if (!normalizedTags.has(String(element.tagName || '').toLowerCase())) return
      if (element.style) element.style.cssText = cssText
      // 保持旧契约：命中指定标签后不再处理其嵌套同名标签。
      return false
    }
  })
  return root
}

export const replaceDomTextNodes = (root, replaceText) => {
  if (typeof replaceText !== 'function') return root
  walkDomDescendants(root, {
    onText(textNode) {
      const nextValue = String(replaceText(textNode.nodeValue || '', textNode) ?? '')
      const parent = textNode.parentNode
      const ownerDocument = textNode.ownerDocument || root?.ownerDocument
      if (parent?.replaceChild && ownerDocument?.createTextNode) {
        parent.replaceChild(ownerDocument.createTextNode(nextValue), textNode)
      } else {
        textNode.nodeValue = nextValue
      }
    }
  })
  return root
}

export const removeDomElements = (root, shouldRemove) => {
  if (typeof shouldRemove !== 'function') return root
  walkDomDescendants(root, {
    onElement(element) {
      if (!shouldRemove(element)) return
      element.parentNode?.removeChild?.(element)
      return false
    }
  })
  return root
}
