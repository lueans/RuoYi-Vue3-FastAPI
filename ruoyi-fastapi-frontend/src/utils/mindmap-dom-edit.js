export function insertMindmapPlainTextAtSelection(
  text,
  target,
  { documentRef = globalThis.document } = {},
) {
  const value = String(text ?? '')
  if (!value || !target || !documentRef?.createTextNode || !documentRef?.getSelection) return false
  const selection = documentRef.getSelection()
  if (!selection || selection.rangeCount <= 0) return false
  const range = selection.getRangeAt(0)
  const ancestor = range.commonAncestorContainer
  if (ancestor !== target && !target.contains?.(ancestor)) return false

  range.deleteContents()
  const textNode = documentRef.createTextNode(value)
  range.insertNode(textNode)
  range.setStartAfter(textNode)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
  return true
}
