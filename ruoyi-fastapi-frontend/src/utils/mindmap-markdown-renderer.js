const VOID_NODES = new Set(['definition'])

export function escapeMindmapMarkdownHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function renderMindmapPlainText(value) {
  const text = escapeMindmapMarkdownHtml(value).replace(/\r\n?|\n/g, '<br>')
  return text ? `<p>${text}</p>` : ''
}

function renderChildren(node, context) {
  return Array.isArray(node?.children)
    ? node.children.map(child => renderNode(child, context)).join('')
    : ''
}

function resolveDefinition(node, context) {
  const identifier = String(node?.identifier || node?.label || '').toLowerCase()
  return identifier ? context.definitions.get(identifier) : null
}

function normalizeUrl(normalizer, value) {
  try {
    return typeof normalizer === 'function' ? normalizer(value) : ''
  } catch {
    return ''
  }
}

function renderLink(node, context, definition = node) {
  const content = renderChildren(node, context)
  const href = normalizeUrl(context.normalizeLink, definition?.url)
  if (!href) return content
  const title = definition?.title
    ? ` title="${escapeMindmapMarkdownHtml(definition.title)}"`
    : ''
  return `<a href="${escapeMindmapMarkdownHtml(href)}"${title} target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${content}</a>`
}

function renderImage(node, context, definition = node) {
  const src = normalizeUrl(context.normalizeImage, definition?.url)
  const alt = escapeMindmapMarkdownHtml(node?.alt || definition?.alt || '')
  if (!src) return alt
  const title = definition?.title
    ? ` title="${escapeMindmapMarkdownHtml(definition.title)}"`
    : ''
  return `<img src="${escapeMindmapMarkdownHtml(src)}" alt="${alt}"${title} loading="lazy" decoding="async" referrerpolicy="no-referrer">`
}

function renderNode(node, context) {
  if (!node || typeof node !== 'object') return ''
  if (VOID_NODES.has(node.type)) return ''

  switch (node.type) {
    case 'root':
      return renderChildren(node, context)
    case 'text':
      return escapeMindmapMarkdownHtml(node.value)
    case 'html':
      return escapeMindmapMarkdownHtml(node.value)
    case 'paragraph':
      return `<p>${renderChildren(node, context)}</p>`
    case 'heading': {
      const depth = Math.min(6, Math.max(1, Number(node.depth) || 1))
      return `<h${depth}>${renderChildren(node, context)}</h${depth}>`
    }
    case 'emphasis':
      return `<em>${renderChildren(node, context)}</em>`
    case 'strong':
      return `<strong>${renderChildren(node, context)}</strong>`
    case 'delete':
      return `<del>${renderChildren(node, context)}</del>`
    case 'inlineCode':
      return `<code>${escapeMindmapMarkdownHtml(node.value).replace(/\r\n?|\n/g, ' ')}</code>`
    case 'code':
      return `<pre><code>${escapeMindmapMarkdownHtml(node.value)}</code></pre>`
    case 'blockquote':
      return `<blockquote>${renderChildren(node, context)}</blockquote>`
    case 'list': {
      const tag = node.ordered ? 'ol' : 'ul'
      const start = node.ordered && Number.isInteger(node.start) && node.start > 1
        ? ` start="${node.start}"`
        : ''
      return `<${tag}${start}>${renderChildren(node, context)}</${tag}>`
    }
    case 'listItem':
      return `<li>${renderChildren(node, context)}</li>`
    case 'thematicBreak':
      return '<hr>'
    case 'break':
      return '<br>'
    case 'link':
      return renderLink(node, context)
    case 'linkReference': {
      const definition = resolveDefinition(node, context)
      return definition ? renderLink(node, context, definition) : renderChildren(node, context)
    }
    case 'image':
      return renderImage(node, context)
    case 'imageReference': {
      const definition = resolveDefinition(node, context)
      return definition
        ? renderImage(node, context, definition)
        : escapeMindmapMarkdownHtml(node.alt || '')
    }
    default:
      if (Array.isArray(node.children)) return renderChildren(node, context)
      return escapeMindmapMarkdownHtml(node.value)
  }
}

export function renderMindmapMarkdownAst(root, options = {}) {
  if (!root || typeof root !== 'object') return ''
  const definitions = new Map()
  const collectDefinitions = node => {
    if (!node || typeof node !== 'object') return
    if (node.type === 'definition') {
      const identifier = String(node.identifier || node.label || '').toLowerCase()
      if (identifier && !definitions.has(identifier)) definitions.set(identifier, node)
    }
    if (Array.isArray(node.children)) node.children.forEach(collectDefinitions)
  }
  collectDefinitions(root)
  return renderNode(root, {
    definitions,
    normalizeLink: options.normalizeLink,
    normalizeImage: options.normalizeImage,
  })
}
