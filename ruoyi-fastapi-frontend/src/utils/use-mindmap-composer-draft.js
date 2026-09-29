import { onScopeDispose, ref, watch } from 'vue'
import { composerDraftScopeKey, createMindmapComposerDraftStorage } from './mindmap-agent-composer-storage.js'

export function useMindmapComposerDraft({ scope, ready, readText, writeText, repository = createMindmapComposerDraftStorage() }) {
  const notice = ref('')
  const persisted = ref(false)
  let boundKey = ''
  let boundScope = null
  let record = null
  let disposed = false
  const storageFailure = () => {
    persisted.value = false
    notice.value = '浏览器无法保存或清除草稿；当前输入仍可使用，离开前请自行复制。'
  }

  function bind() {
    if (disposed) return
    const current = scope()
    const key = composerDraftScopeKey(current)
    if (!key) {
      // Never flush the previous owner's text into a new/unauthenticated scope.
      if (boundKey) writeText('')
      boundKey = ''
      boundScope = null
      record = null
      persisted.value = false
      notice.value = ''
      return
    }
    if (!ready() || key === boundKey) return
    const initial = !boundKey
    boundKey = key
    boundScope = { ...current }
    record = null
    persisted.value = false
    notice.value = ''
    if (!initial) writeText('')
    try {
      record = repository.read(boundScope)
      if (record) {
        persisted.value = true
        writeText(record.text)
        notice.value = '已恢复此会话未发送的文字；请确认 Agent、模式与范围，附件需重新检查。'
      }
    } catch { storageFailure() }
  }

  function update(text) {
    writeText(text)
    persisted.value = false
    if (disposed || !boundKey || composerDraftScopeKey(scope()) !== boundKey) return false
    record = null
    try {
      record = repository.write(boundScope, text)
      persisted.value = Boolean(record)
      if (!record) notice.value = ''
      else if (notice.value.startsWith('浏览器无法')) notice.value = ''
      return true
    } catch { storageFailure(); return false }
  }

  function capture(prompt) {
    if (disposed || !boundKey || composerDraftScopeKey(scope()) !== boundKey
      || typeof prompt !== 'string' || !prompt.trim() || readText().trim() !== prompt.trim()) return null
    if (!record || record.text !== readText()) update(readText())
    return record?.text.trim() === prompt.trim() ? { scope: { ...boundScope }, id: record.id } : null
  }

  function consume(receipt) {
    if (disposed || !receipt?.id || !composerDraftScopeKey(receipt.scope)
      || scope()?.ownerId !== receipt.scope.ownerId) return false
    try {
      const removed = repository.remove(receipt.scope, receipt.id)
      if (composerDraftScopeKey(receipt.scope) === boundKey && record?.id === receipt.id) {
        // Do not erase programmatically replaced text which wasn't this send.
        if (readText() === record.text) writeText('')
        record = null
        persisted.value = false
        notice.value = ''
      }
      return removed
    } catch { storageFailure(); return false }
  }

  // Bind only a settled identity. Writes happen only on user edits/capture,
  // never on resetNewJob's intermediate clears or task snapshot changes.
  watch([() => composerDraftScopeKey(scope()), ready], bind, { immediate: true, flush: 'post' })
  onScopeDispose(() => { disposed = true })
  return { notice, persisted, update, capture, consume }
}
