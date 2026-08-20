export const estimateHistoryEntryBytes = entry =>
  typeof entry === 'string' ? entry.length * 2 : 0

const normalizeCountLimit = value => {
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(1, Math.floor(number)) : Infinity
}

const normalizeByteLimit = value => {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : Infinity
}

// Mutates and returns the supplied history list. Count and memory limits evict
// oldest snapshots first; the newest snapshot is always retained even when a
// single very large document exceeds the configured memory budget.
export const trimHistoryEntries = (entries, maxCount, maxBytes) => {
  if (!Array.isArray(entries) || entries.length === 0) return entries
  const countLimit = normalizeCountLimit(maxCount)
  const byteLimit = normalizeByteLimit(maxBytes)

  if (entries.length > countLimit) {
    entries.splice(0, entries.length - countLimit)
  }

  let totalBytes = 0
  for (let index = 0; index < entries.length; index += 1) {
    totalBytes += estimateHistoryEntryBytes(entries[index])
  }

  let removeCount = 0
  while (
    removeCount < entries.length - 1
    && totalBytes > byteLimit
  ) {
    totalBytes -= estimateHistoryEntryBytes(entries[removeCount])
    removeCount += 1
  }
  if (removeCount > 0) entries.splice(0, removeCount)
  return entries
}
