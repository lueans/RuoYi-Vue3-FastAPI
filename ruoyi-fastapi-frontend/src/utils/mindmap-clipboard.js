export async function copyMindmapText(
  text,
  {
    clipboard = globalThis.navigator?.clipboard,
    documentRef = globalThis.document,
  } = {},
) {
  const value = String(text ?? '')
  if (!value) throw new Error('没有可复制的内容')
  if (clipboard?.writeText) {
    try {
      await clipboard.writeText(value)
      return true
    } catch {
      // Permission-denied and non-secure contexts may still use selection copy.
    }
  }
  if (!documentRef?.body || typeof documentRef.execCommand !== 'function') {
    throw new Error('当前浏览器不支持自动复制')
  }

  const activeElement = documentRef.activeElement
  const textarea = documentRef.createElement('textarea')
  textarea.value = value
  textarea.readOnly = true
  textarea.setAttribute('aria-hidden', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  documentRef.body.appendChild(textarea)
  textarea.select()
  let copied = false
  try {
    copied = documentRef.execCommand('copy') === true
  } finally {
    textarea.remove()
    activeElement?.focus?.()
  }
  if (!copied) throw new Error('复制失败，请手动选择内容')
  return true
}

export async function copyMindmapPngBlob(
  blob,
  {
    clipboard = globalThis.navigator?.clipboard,
    ClipboardItemCtor = globalThis.ClipboardItem,
  } = {},
) {
  if (!(blob instanceof Blob) || blob.type !== 'image/png') {
    throw new Error('没有可复制的 PNG 图片')
  }
  if (!clipboard?.write || typeof ClipboardItemCtor !== 'function') {
    throw new Error('当前浏览器不支持复制图片')
  }
  await clipboard.write([new ClipboardItemCtor({ 'image/png': blob })])
  return true
}
