// Attachments are read locally. Only the extracted plain text is sent to the AI.
export const MINDMAP_AI_ATTACHMENT_ACCEPT = '.txt,.md,.markdown,.json,.csv,.pdf,.docx'
export const MAX_MINDMAP_AI_ATTACHMENTS = 5
export const MAX_MINDMAP_AI_ATTACHMENT_BYTES = 10 * 1024 * 1024
export const MAX_MINDMAP_AI_ATTACHMENT_CHARS = 50_000
export const MAX_MINDMAP_AI_ATTACHMENT_TOTAL_CHARS = 100_000
export const MAX_MINDMAP_AI_PDF_PAGES = 100

const MAX_DOCX_ENTRIES = 512
const MAX_DOCX_ENTRY_BYTES = 16 * 1024 * 1024
const MAX_DOCX_EXPANDED_BYTES = 32 * 1024 * 1024
const MEDIA_TYPES = {
  txt: 'text/plain',
  md: 'text/markdown',
  markdown: 'text/markdown',
  json: 'application/json',
  csv: 'text/csv',
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

class AttachmentError extends Error {}

function rejectAttachment(message) {
  throw new AttachmentError(message)
}

function attachmentExtension(file) {
  const name = String(file?.name || '')
  if (!name.trim() || name.length > 255 || /[\u0000-\u001f\u007f]/u.test(name)) {
    rejectAttachment('附件名称无效，请重命名后再上传')
  }
  const extension = name.split('.').pop().toLowerCase()
  if (!Object.hasOwn(MEDIA_TYPES, extension)) {
    rejectAttachment('暂不支持此附件格式，请选择 TXT、Markdown、JSON、CSV、PDF 或 DOCX 文件')
  }
  if (!Number.isSafeInteger(file.size) || file.size <= 0) {
    rejectAttachment(`“${name}”是空文件或无法读取`)
  }
  if (file.size > MAX_MINDMAP_AI_ATTACHMENT_BYTES) {
    rejectAttachment(`“${name}”超过单个附件 10 MB 的限制`)
  }
  return extension
}

function validateText(text, name) {
  if (typeof text !== 'string' || !text.trim()) {
    rejectAttachment(`“${name}”未读取到可用文字，请检查文件内容`)
  }
  if (text.length > MAX_MINDMAP_AI_ATTACHMENT_CHARS) {
    rejectAttachment(`“${name}”的文字超过 50,000 字符，请拆分后再上传`)
  }
  if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/u.test(text)) {
    rejectAttachment(`“${name}”包含无法识别的二进制内容，请转换为可读文本后再上传`)
  }
}

export function validateMindmapAiAttachments(list) {
  if (!Array.isArray(list)) rejectAttachment('附件列表无效，请重新选择文件')
  if (list.length > MAX_MINDMAP_AI_ATTACHMENTS) rejectAttachment('每次最多添加 5 个附件')
  let characters = 0
  for (const file of list) {
    attachmentExtension(file)
    validateText(file.text, file.name)
    characters += file.text.length
  }
  if (characters > MAX_MINDMAP_AI_ATTACHMENT_TOTAL_CHARS) {
    rejectAttachment('附件文字总量超过 100,000 字符，请减少附件或拆分内容')
  }
  return true
}

function decodeText(buffer, name) {
  const bytes = new Uint8Array(buffer)
  let encoding = 'utf-8'
  if (bytes[0] === 0xff && bytes[1] === 0xfe) encoding = 'utf-16le'
  if (bytes[0] === 0xfe && bytes[1] === 0xff) encoding = 'utf-16be'
  try {
    return new TextDecoder(encoding, { fatal: true }).decode(bytes)
  } catch {
    rejectAttachment(`“${name}”的文字编码无法识别，请另存为 UTF-8 后再上传`)
  }
}

async function extractPdfText(buffer) {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  let BinaryDataFactory
  if (typeof window !== 'undefined') {
    // Vite emits a same-origin worker asset; no CDN or document URLs are fetched.
    const worker = await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url')
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default
    // Include CJK character maps and standard fonts as local build assets. A
    // PDF may only ask for one of these allowlisted resources, never a URL.
    const resources = import.meta.glob('/node_modules/pdfjs-dist/{cmaps/*.bcmap,standard_fonts/*.{pfb,ttf}}', {
      query: '?url', import: 'default', eager: true,
    })
    BinaryDataFactory = class {
      async fetch({ kind, filename }) {
        const directory = { cMapUrl: 'cmaps', standardFontDataUrl: 'standard_fonts' }[kind]
        const resource = directory && resources[`/node_modules/pdfjs-dist/${directory}/${filename}`]
        if (!resource) throw new Error('PDF 请求了不支持的字体资源')
        const response = await fetch(resource)
        if (!response.ok) throw new Error('PDF 字体资源加载失败，请刷新页面后重试')
        return new Uint8Array(await response.arrayBuffer())
      }
    }
  }
  const task = pdfjs.getDocument({
    data: new Uint8Array(buffer),
    isEvalSupported: false,
    useWorkerFetch: false,
    useSystemFonts: false,
    disableFontFace: true,
    useWasm: false,
    enableXfa: false,
    stopAtErrors: true,
    BinaryDataFactory,
  })
  try {
    const document = await task.promise
    if (document.numPages > MAX_MINDMAP_AI_PDF_PAGES) {
      rejectAttachment('PDF 超过 100 页，请拆分后再上传')
    }
    const pages = []
    let characters = 0
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber)
      try {
        const content = await page.getTextContent()
        const text = content.items
          .filter(item => typeof item.str === 'string')
          .map(item => item.str + (item.hasEOL ? '\n' : ' '))
          .join('')
          .trim()
        characters += text.length + (pages.length ? 2 : 0)
        if (characters > MAX_MINDMAP_AI_ATTACHMENT_CHARS) {
          rejectAttachment('PDF 的文字超过 50,000 字符，请拆分后再上传')
        }
        pages.push(text)
      } finally {
        page.cleanup()
      }
    }
    const text = pages.join('\n\n').trim()
    if (!text) rejectAttachment('PDF 中没有可提取的文字；扫描件或图片 PDF 请先通过 OCR 转为文字')
    return text
  } catch (error) {
    if (error instanceof AttachmentError) throw error
    if (error?.name === 'PasswordException') rejectAttachment('PDF 已加密，请解除密码保护后再上传')
    rejectAttachment('PDF 无法解析，文件可能已损坏或包含不支持的内容')
  } finally {
    await task.destroy()
  }
}

// Inspect the ZIP directory before inflating any DOCX entries. ZIP64, encrypted
// archives, duplicate names and unsafe paths are intentionally unsupported.
function inspectDocxDirectory(buffer) {
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  let end = -1
  for (let offset = bytes.length - 22; offset >= Math.max(0, bytes.length - 65_557); offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50 && offset + 22 + view.getUint16(offset + 20, true) === bytes.length) {
      end = offset
      break
    }
  }
  if (end < 0) rejectAttachment('DOCX 文件已损坏，无法读取文档结构')
  const count = view.getUint16(end + 10, true)
  const directorySize = view.getUint32(end + 12, true)
  let offset = view.getUint32(end + 16, true)
  if (view.getUint16(end + 4, true) || view.getUint16(end + 6, true) || view.getUint16(end + 8, true) !== count || offset + directorySize !== end) {
    rejectAttachment('DOCX 压缩结构不受支持，请在 Word 中重新保存后上传')
  }
  if (count > MAX_DOCX_ENTRIES) rejectAttachment('DOCX 内部文件过多，请简化文档后再上传')
  const entries = new Map()
  let total = 0
  for (let index = 0; index < count; index += 1) {
    if (offset + 46 > end || view.getUint32(offset, true) !== 0x02014b50) rejectAttachment('DOCX 文件已损坏，无法读取文档结构')
    const flags = view.getUint16(offset + 8, true)
    const method = view.getUint16(offset + 10, true)
    const size = view.getUint32(offset + 24, true)
    const nameLength = view.getUint16(offset + 28, true)
    const nextOffset = offset + 46 + nameLength + view.getUint16(offset + 30, true) + view.getUint16(offset + 32, true)
    if (nextOffset > end || flags & 1 || ![0, 8].includes(method)) rejectAttachment('DOCX 已加密、损坏或使用不支持的压缩方式')
    const name = new TextDecoder().decode(bytes.subarray(offset + 46, offset + 46 + nameLength))
    if (!name || entries.has(name) || name.startsWith('/') || name.includes('\\') || name.split('/').includes('..')) {
      rejectAttachment('DOCX 包含无效的内部路径，请重新保存后再上传')
    }
    total += size
    if (size > MAX_DOCX_ENTRY_BYTES || total > MAX_DOCX_EXPANDED_BYTES) {
      rejectAttachment('DOCX 解压后的内容过大，请移除大图片或拆分文档后再上传')
    }
    entries.set(name, size)
    offset = nextOffset
  }
  if (offset !== end || !entries.has('[Content_Types].xml') || !entries.has('word/document.xml')) {
    rejectAttachment('这不是有效的 DOCX 文档，请在 Word 中重新保存后上传')
  }
  return entries
}

function verifyExpandedEntry(entry, expectedSize) {
  return new Promise((resolve, reject) => {
    let received = 0
    let settled = false
    const stream = entry.internalStream('uint8array')
    const fail = message => {
      if (settled) return
      settled = true
      stream.pause()
      reject(new AttachmentError(message))
    }
    stream.on('data', chunk => {
      received += chunk.byteLength
      if (received > expectedSize || received > MAX_DOCX_ENTRY_BYTES) {
        fail('DOCX 解压内容超过安全限制，请重新保存或拆分文档')
      }
    })
    stream.on('error', () => fail('DOCX 文件已损坏，无法解压内容'))
    stream.on('end', () => {
      if (settled) return
      if (received !== expectedSize) return fail('DOCX 文件已损坏，内容大小校验失败')
      settled = true
      resolve()
    })
    stream.resume()
  })
}

async function extractDocxText(buffer) {
  const entries = inspectDocxDirectory(buffer)
  try {
    const { default: JSZip } = await import('jszip')
    const archive = await JSZip.loadAsync(buffer, { createFolders: false })
    for (const [name, size] of entries) {
      const entry = archive.files[name]
      if (!entry) rejectAttachment('DOCX 文件已损坏，内部结构不完整')
      if (!entry.dir) await verifyExpandedEntry(entry, size)
    }
    const imported = await import('mammoth/mammoth.browser.js')
    const mammoth = imported.default || imported
    const result = await mammoth.extractRawText({ arrayBuffer: buffer }, { externalFileAccess: false })
    return result.value
  } catch (error) {
    if (error instanceof AttachmentError) throw error
    rejectAttachment('DOCX 无法解析，文件可能已损坏；请在 Word 中重新保存后上传')
  }
}

export async function readMindmapAiAttachment(file) {
  const extension = attachmentExtension(file)
  try {
    const buffer = await file.arrayBuffer()
    if (buffer.byteLength !== file.size) rejectAttachment('附件读取不完整，请重新选择文件')
    const text = extension === 'pdf'
      ? await extractPdfText(buffer)
      : extension === 'docx'
        ? await extractDocxText(buffer)
        : decodeText(buffer, file.name)
    validateText(text, file.name)
    const identity = new TextEncoder().encode(JSON.stringify([file.name, file.size, MEDIA_TYPES[extension], text]))
    const digest = await globalThis.crypto.subtle.digest('SHA-256', identity)
    const id = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
    return {
      id: `attachment-${id}`,
      name: file.name,
      size: file.size,
      mediaType: MEDIA_TYPES[extension],
      text,
    }
  } catch (error) {
    if (error instanceof AttachmentError) throw error
    rejectAttachment(`“${file.name}”读取失败，请检查文件后重新上传`)
  }
}
