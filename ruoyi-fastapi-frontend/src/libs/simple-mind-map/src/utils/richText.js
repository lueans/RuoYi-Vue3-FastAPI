import createDOMPurify from 'dompurify'
import { getSafeMindMapHyperlink } from './hyperlink.js'

const ALLOWED_TAGS = [
  'a',
  'b',
  'blockquote',
  'br',
  'code',
  'div',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'i',
  'li',
  'ol',
  'p',
  'pre',
  's',
  'span',
  'strike',
  'strong',
  'sub',
  'sup',
  'u',
  'ul'
]

const ALLOWED_ATTRIBUTES = [
  'class',
  'data-list',
  'data-value',
  'href',
  'rel',
  'style',
  'target'
]

const SAFE_STYLE_PROPERTIES = new Set([
  'background-color',
  'color',
  'font-family',
  'font-size',
  'font-style',
  'font-weight',
  'text-align',
  'text-decoration'
])

const UNSAFE_STYLE_VALUE_PATTERN = /(?:@import|behavior\s*:|expression\s*\(|javascript\s*:|-moz-binding|url\s*\(|var\s*\(|\\)/i
const SAFE_COLOR_PATTERN = /^(?:#[\da-f]{3,8}|[a-z]{1,32}|(?:rgb|rgba|hsl|hsla)\([\d.,%+\-\s/]+\))$/i
const SAFE_FONT_FAMILY_PATTERN = /^[\p{L}\p{N}\s,'"-]{1,160}$/u
const SAFE_FONT_SIZE_PATTERN = /^\d{1,3}(?:\.\d+)?(?:px|em|rem|%)$/i
const SAFE_FONT_WEIGHT_PATTERN = /^(?:normal|bold|bolder|lighter|[1-9]00)$/i
const SAFE_FONT_STYLE_PATTERN = /^(?:normal|italic|oblique)$/i
const SAFE_TEXT_ALIGN_PATTERN = /^(?:left|right|center|justify|start|end)$/i
const SAFE_TEXT_DECORATION_PATTERN = /^(?:none|underline|line-through|underline line-through|line-through underline)$/i
const SAFE_QUILL_CLASS_PATTERN = /^ql-[a-z\d_-]{1,80}$/i
const SAFE_LIST_TYPES = new Set(['bullet', 'checked', 'ordered', 'unchecked'])
const MAX_FORMULA_LENGTH = 4096
const CONTROL_CHARACTER_PATTERN = /[\u0000-\u001F\u007F]/

const PURIFY_CONFIG = {
  ALLOWED_ATTR: ALLOWED_ATTRIBUTES,
  ALLOWED_TAGS,
  ALLOW_ARIA_ATTR: false,
  ALLOW_DATA_ATTR: false,
  KEEP_CONTENT: true,
  RETURN_TRUSTED_TYPE: false
}

let activeWindow = null
let purifier = null

const escapeHtml = value => String(value)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;')

const getWindow = () => {
  if (globalThis.window?.document) return globalThis.window
  if (globalThis.document?.defaultView) return globalThis.document.defaultView
  return null
}

const getPurifier = windowObject => {
  if (purifier && activeWindow === windowObject) return purifier
  activeWindow = windowObject
  purifier = createDOMPurify(windowObject)
  return purifier
}

const isSafeStyleValue = (property, value) => {
  if (!value || value.length > 200 || UNSAFE_STYLE_VALUE_PATTERN.test(value)) {
    return false
  }
  switch (property) {
    case 'background-color':
    case 'color':
      return SAFE_COLOR_PATTERN.test(value)
    case 'font-family':
      return SAFE_FONT_FAMILY_PATTERN.test(value)
    case 'font-size':
      return SAFE_FONT_SIZE_PATTERN.test(value)
    case 'font-style':
      return SAFE_FONT_STYLE_PATTERN.test(value)
    case 'font-weight':
      return SAFE_FONT_WEIGHT_PATTERN.test(value)
    case 'text-align':
      return SAFE_TEXT_ALIGN_PATTERN.test(value)
    case 'text-decoration':
      return SAFE_TEXT_DECORATION_PATTERN.test(value)
    default:
      return false
  }
}

export const sanitizeRichTextStyle = value => String(value || '')
  .split(';')
  .map(declaration => declaration.trim())
  .filter(Boolean)
  .reduce((result, declaration) => {
    const separatorIndex = declaration.indexOf(':')
    if (separatorIndex <= 0) return result
    const property = declaration.slice(0, separatorIndex).trim().toLowerCase()
    const styleValue = declaration.slice(separatorIndex + 1).trim()
    if (
      SAFE_STYLE_PROPERTIES.has(property)
      && isSafeStyleValue(property, styleValue)
    ) {
      result.push(`${property}: ${styleValue}`)
    }
    return result
  }, [])
  .join('; ')

const sanitizeElementAttributes = element => {
  const className = String(element.getAttribute('class') || '')
    .split(/\s+/)
    .filter(token => SAFE_QUILL_CLASS_PATTERN.test(token))
    .join(' ')
  if (className) element.setAttribute('class', className)
  else element.removeAttribute('class')

  const style = sanitizeRichTextStyle(element.getAttribute('style'))
  if (style) element.setAttribute('style', style)
  else element.removeAttribute('style')

  if (element.tagName === 'A') {
    const href = getSafeMindMapHyperlink(element.getAttribute('href'))
    if (href) {
      element.setAttribute('href', href)
      element.setAttribute('target', '_blank')
      element.setAttribute('rel', 'noopener noreferrer')
    } else {
      element.removeAttribute('href')
      element.removeAttribute('target')
      element.removeAttribute('rel')
    }
  } else {
    element.removeAttribute('href')
    element.removeAttribute('target')
    element.removeAttribute('rel')
  }

  const formulaValue = element.getAttribute('data-value')
  const isFormula = element.tagName === 'SPAN'
    && element.classList.contains('ql-formula')
  if (
    !isFormula
    || !formulaValue
    || formulaValue.length > MAX_FORMULA_LENGTH
    || CONTROL_CHARACTER_PATTERN.test(formulaValue)
  ) {
    element.removeAttribute('data-value')
  }

  const listType = element.getAttribute('data-list')
  if (element.tagName !== 'LI' || !SAFE_LIST_TYPES.has(listType)) {
    element.removeAttribute('data-list')
  }
}

/**
 * 净化节点富文本。DOMPurify 先移除危险标签和属性，再收紧 Quill 样式、
 * class、公式及链接协议。无 DOM 环境时按纯文本转义，保持失败关闭。
 */
export const sanitizeRichTextHtml = value => {
  const source = String(value ?? '')
  if (!source) return ''
  const windowObject = getWindow()
  if (!windowObject) return escapeHtml(source)

  const sanitized = getPurifier(windowObject).sanitize(source, PURIFY_CONFIG)
  const container = windowObject.document.createElement('div')
  container.innerHTML = String(sanitized)
  container.querySelectorAll('*').forEach(sanitizeElementAttributes)
  return container.innerHTML
}
