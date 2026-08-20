import { normalizeMindMapHyperlink } from '../libs/simple-mind-map/src/utils/hyperlink.js'
import { normalizeMindmapImageUrl } from './mindmap-image.js'
import {
  renderMindmapMarkdownAst,
  renderMindmapPlainText,
} from './mindmap-markdown-renderer.js'

export const MINDMAP_NOTE_MAX_LENGTH = 20000

let markdownParserPromise

function loadMarkdownParser() {
  if (!markdownParserPromise) {
    markdownParserPromise = import('mdast-util-from-markdown').catch(error => {
      markdownParserPromise = null
      throw error
    })
  }
  return markdownParserPromise
}

export async function renderMindmapMarkdown(value) {
  const source = String(value ?? '').slice(0, MINDMAP_NOTE_MAX_LENGTH)
  if (!source) return ''

  try {
    const { fromMarkdown } = await loadMarkdownParser()
    return renderMindmapMarkdownAst(fromMarkdown(source), {
      normalizeLink: normalizeMindMapHyperlink,
      normalizeImage: normalizeMindmapImageUrl,
    })
  } catch {
    return renderMindmapPlainText(source)
  }
}
