const SVG_NAMESPACE = 'http://www.w3.org/2000/svg'

export function addSafeSvgTitle(parent, value, options = {}) {
  if (!parent?.node || value === undefined || value === null || value === '') return null
  const ownerDocument = parent.node.ownerDocument || globalThis.document
  if (!ownerDocument?.createElementNS) return null
  const title = ownerDocument.createElementNS(SVG_NAMESPACE, 'title')
  title.textContent = String(value)
  if (options.prepend && parent.node.firstChild) {
    parent.node.insertBefore(title, parent.node.firstChild)
  } else {
    parent.node.appendChild(title)
  }
  return title
}
