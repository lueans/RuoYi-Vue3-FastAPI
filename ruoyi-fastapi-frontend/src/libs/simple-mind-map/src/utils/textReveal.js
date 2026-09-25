// Presentation-only text. The authoritative text is measured while detached;
// hidden suffixes reserve its geometry without exposing it on the canvas.
const segmenter = typeof Intl?.Segmenter === 'function'
  ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
  : null

export function textGraphemes(text) {
  const value = String(text ?? '')
  return segmenter
    ? Array.from(segmenter.segment(value), item => item.segment)
    : Array.from(value)
}

function richTextTemplate(text) {
  const template = document.createElement('template')
  template.innerHTML = text
  return template
}

export function plainRevealText(text, richText = false) {
  const value = String(text ?? '')
  return richText ? richTextTemplate(value).content.textContent : value
}

export function nextRevealedText(currentText, targetText, richText = false, currentRichText = richText) {
  const current = textGraphemes(plainRevealText(currentText, currentRichText))
  const target = textGraphemes(plainRevealText(targetText, richText))
  let common = 0
  while (common < current.length && current[common] === target[common]) common += 1
  const prefix = target.slice(0, common + 1).join('')
  if (common + 1 >= target.length) return targetText
  if (!richText) return prefix
  // Never slice HTML markup: retain valid formatting and truncate text nodes.
  const template = richTextTemplate(targetText)
  const walker = document.createTreeWalker(template.content, 4 /* SHOW_TEXT */)
  let remaining = prefix.length
  while (walker.nextNode()) {
    const node = walker.currentNode
    const length = node.data.length
    node.data = node.data.slice(0, remaining)
    remaining = Math.max(0, remaining - length)
  }
  return template.innerHTML
}

export function createTextReveal(textData, targetText, visibleText, richText = false) {
  const element = textData.node.node
  const walker = document.createTreeWalker(element, 4 /* SHOW_TEXT */)
  const textNodes = []
  while (walker.nextNode()) textNodes.push(walker.currentNode)
  const parts = textNodes.map(node => {
    const text = node.data
    const svg = node.parentNode.namespaceURI === 'http://www.w3.org/2000/svg'
    const hidden = document.createElementNS(
      svg ? 'http://www.w3.org/2000/svg' : 'http://www.w3.org/1999/xhtml',
      svg ? 'tspan' : 'span',
    )
    hidden.style.visibility = 'hidden'
    hidden.setAttribute('aria-hidden', 'true')
    node.after(hidden)
    return { node, hidden, text }
  })
  const reveal = {
    targetText,
    setVisible(text) {
      // SVG wrapping removes source newlines; HTML keeps its text nodes.
      const plainText = plainRevealText(text, richText)
      let remaining = (richText ? plainText : plainText.replace(/\n/g, '')).length
      for (const part of parts) {
        // The SVG renderer uses a BOM to give an empty line height; it is a
        // layout placeholder, not one of the source text's characters.
        if (!richText && part.text === '\uFEFF') continue
        const visible = part.text.slice(0, remaining)
        if (part.node.data !== visible) part.node.data = visible
        const suffix = part.text.slice(remaining)
        if (part.hidden.textContent !== suffix) part.hidden.textContent = suffix
        remaining = Math.max(0, remaining - part.text.length)
      }
    },
  }
  reveal.setVisible(visibleText)
  return reveal
}
