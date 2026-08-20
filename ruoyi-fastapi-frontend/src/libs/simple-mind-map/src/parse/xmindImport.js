export const MAX_XMIND_DOCUMENT_SIZE = 20 * 1024 * 1024
export const MAX_XMIND_ARCHIVE_SIZE = 100 * 1024 * 1024
export const MAX_XMIND_ARCHIVE_ENTRIES = 2000
const MAX_XML_NODES = 250000
const MAX_XML_DEPTH = 512
const UNSAFE_XML_DECLARATION = /<!\s*(?:DOCTYPE|ENTITY)\b/i

export function assertXmindDocumentSize(content, label = 'XMind 文档') {
  if (typeof content !== 'string') throw new Error(`${label}内容无效`)
  if (new Blob([content]).size > MAX_XMIND_DOCUMENT_SIZE) {
    throw new Error(`${label}解压后不能超过 20MB`)
  }
  return content
}

export function validateXmindArchive(files) {
  const entries = Object.values(files || {}).filter(entry => entry && !entry.dir)
  if (entries.length > MAX_XMIND_ARCHIVE_ENTRIES) {
    throw new Error('XMind 压缩包文件数量异常')
  }

  let totalSize = 0
  for (const entry of entries) {
    const size = Number(entry?._data?.uncompressedSize)
    if (!Number.isFinite(size) || size < 0) continue
    if (size > MAX_XMIND_DOCUMENT_SIZE) {
      throw new Error(`XMind 压缩项 ${entry.name || ''} 解压后过大`)
    }
    totalSize += size
    if (totalSize > MAX_XMIND_ARCHIVE_SIZE) {
      throw new Error('XMind 压缩包解压后总体积不能超过 100MB')
    }
  }
  return true
}

function convertElement(element, state, depth) {
  if (depth > MAX_XML_DEPTH) throw new Error('XMind XML 嵌套层级异常')
  state.nodeCount += 1
  if (state.nodeCount > MAX_XML_NODES) throw new Error('XMind XML 节点数量异常')

  const result = {
    type: 'element',
    name: element.nodeName,
  }
  const attributes = {}
  for (const attribute of Array.from(element.attributes || [])) {
    attributes[attribute.name] = attribute.value
  }
  if (Object.keys(attributes).length) result.attributes = attributes

  const elements = []
  for (const child of Array.from(element.childNodes || [])) {
    if (child.nodeType === 1) {
      elements.push(convertElement(child, state, depth + 1))
    } else if ((child.nodeType === 3 || child.nodeType === 4) && child.nodeValue?.trim()) {
      state.nodeCount += 1
      if (state.nodeCount > MAX_XML_NODES) throw new Error('XMind XML 节点数量异常')
      // The legacy XMind transformer consumes xml-js' text shape. Treat CDATA
      // as text as well so valid XMind 8 titles are not silently discarded.
      elements.push({ type: 'text', text: child.nodeValue })
    }
  }
  if (elements.length) result.elements = elements
  return result
}

export function parseXmindXml(xml, { DOMParserImpl = globalThis.DOMParser } = {}) {
  assertXmindDocumentSize(xml, 'XMind XML')
  if (UNSAFE_XML_DECLARATION.test(xml)) {
    throw new Error('XMind XML 不允许 DTD 或实体声明')
  }
  if (typeof DOMParserImpl !== 'function') {
    throw new Error('当前浏览器不支持 XML 导入')
  }

  const document = new DOMParserImpl().parseFromString(xml, 'application/xml')
  const parserErrors = document?.getElementsByTagName?.('parsererror')
  if (
    !document?.documentElement
    || document.documentElement.nodeName === 'parsererror'
    || parserErrors?.length
  ) {
    throw new Error('XMind XML 格式无效')
  }

  return {
    elements: [convertElement(document.documentElement, { nodeCount: 0 }, 0)],
  }
}
