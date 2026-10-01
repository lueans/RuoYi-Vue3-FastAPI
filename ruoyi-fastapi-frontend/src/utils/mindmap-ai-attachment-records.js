// Display receipts only: never persist attachment bodies or use these fields
// as request input, authorization, or evidence that a model read the file.
export function formatAttachmentSize(size) {
  if (typeof size !== 'number' || !Number.isFinite(size) || size < 0) return ''
  if (size < 1024) return `${Math.round(size)} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${Number((size / (1024 * 1024)).toFixed(1))} MB`
}

export function buildMindmapAiAttachmentMetadata(attachments = []) {
  return (Array.isArray(attachments) ? attachments : []).slice(0, 5)
    .filter(file => file && typeof file.name === 'string' && file.name.trim())
    .map(file => {
      const metadata = {
        id: typeof file.id === 'string' ? file.id.slice(0, 100) : '',
        name: file.name.slice(0, 255),
        size: Number.isSafeInteger(file.size) && file.size >= 0 ? file.size : undefined,
        mediaType: typeof file.mediaType === 'string' ? file.mediaType.slice(0, 128) : '',
      }
      // Match the backend's Unicode code-point count, including non-BMP text.
      const count = typeof file.text === 'string' && file.text.trim()
        ? Array.from(file.text).length : undefined
      if (count > 0 && count <= 50_000) {
        metadata.parsing = { status: 'parsed', characterCount: count }
      } else if (!Object.hasOwn(file, 'text') && file.parsing?.status === 'parsed'
        && Number.isSafeInteger(file.parsing.characterCount)
        && file.parsing.characterCount > 0 && file.parsing.characterCount <= 50_000) {
        // The server has removed private text and supplied a bounded receipt.
        metadata.parsing = { status: 'parsed', characterCount: file.parsing.characterCount }
      } else {
        metadata.parsing = { status: 'unknown' }
      }
      return metadata
    })
}
