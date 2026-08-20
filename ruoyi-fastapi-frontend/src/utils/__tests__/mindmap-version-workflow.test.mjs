import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(
  new URL('../../components/MindMap/VersionHistory.vue', import.meta.url),
  'utf8'
)

test('version list ignores stale tab and pagination responses and exposes retry state', () => {
  assert.match(source, /const requestId = \+\+loadRequestId/)
  assert.match(source, /requestId !== loadRequestId \|\| !componentActive/)
  assert.match(source, /loadError\.value = e\?\.message \|\| '版本列表加载失败'/)
  assert.match(source, /role="alert"/)
  assert.match(source, /@click="loadVersions">重新加载/)
})

test('version operations share one busy lock and destructive actions cannot overlap', () => {
  assert.match(source, /const operationType = ref\(''\)/)
  assert.match(source, /const isOperating = computed\(\(\) => Boolean\(operationType\.value\)\)/)
  assert.match(source, /let operationSequence = 0/)
  assert.match(source, /beginOperation\(`confirm-restore:\$\{versionId\}`\)/)
  assert.match(source, /updateOperation\(operationToken, `restore:\$\{versionId\}`\)/)
  assert.match(source, /beginOperation\(`confirm-delete:\$\{versionId\}`\)/)
  assert.match(source, /updateOperation\(operationToken, `delete:\$\{versionId\}`\)/)
  assert.match(source, /if \(token === operationSequence\) operationType\.value = ''/)
  assert.match(source, /:disabled="isOperating"/)
})

test('restoring a version flushes current edits before the irreversible request', () => {
  const flushIndex = source.indexOf('await session.flushChanges()')
  const restoreIndex = source.indexOf('await restoreVersion(versionId)')

  assert.ok(flushIndex > 0)
  assert.ok(restoreIndex > flushIndex)
  assert.match(source, /当前修改尚未成功保存，暂不能恢复历史版本/)
})

test('preview exit restores the full document before resuming Yjs and tracking', () => {
  assert.match(source, /function applyFullDataAndWait/)
  assert.match(source, /node_tree_render_end/)
  assert.match(source, /if \(state\) await applyFullDataAndWait\(state, 1500, previewSession\?\.mindMap\)/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*exitPreview\(\{ notify: false \}\)/)
  const applyIndex = source.indexOf('if (state) await applyFullDataAndWait(state, 1500, previewSession?.mindMap)')
  const resumeIndex = source.indexOf('previewSession?.yjsSync?.resume()', applyIndex)
  const trackingIndex = source.indexOf("emit('change-tracking', false)", applyIndex)
  assert.ok(resumeIndex > applyIndex)
  assert.ok(trackingIndex > resumeIndex)
})

test('历史文档在替换画布前加载实际需要的复杂渲染插件', () => {
  const ensureIndex = source.indexOf('await ensureMindmapDocumentPlugins(data, mindMap)')
  const applyIndex = source.indexOf('mindMap.setFullData(data)', ensureIndex)

  assert.ok(ensureIndex > 0)
  assert.ok(applyIndex > ensureIndex)
  assert.match(source, /await applyFullDataAndWait\(\{[\s\S]*root: versionData\.nodeTree/)
})

test('version operations capture the editor session and ignore late responses after navigation', () => {
  assert.match(source, /function captureSession\(\)/)
  assert.match(source, /function isCurrentSession\(session\)/)
  assert.match(source, /session\.mindmapId === props\.mindmapId/)
  assert.match(source, /session\.mindMap === props\.mindMap/)
  assert.match(source, /const res = await getVersionDetail\(versionId\)[\s\S]*if \(!isCurrentSession\(session\)\) return/)
  assert.match(source, /await session\.flushChanges\(\)[\s\S]*if \(!isCurrentSession\(session\)\) return[\s\S]*await restoreVersion\(versionId\)/)
  assert.match(source, /getMindmap\(session\.mindmapId\)/)
  assert.match(source, /await deleteVersion\(versionId\)[\s\S]*if \(!isCurrentSession\(session\)\) return/)
})

test('version confirmations lock before dialogs and only act on current listed targets', () => {
  const saveLockIndex = source.indexOf("beginOperation('confirm-save')")
  const saveDialogIndex = source.indexOf("ElMessageBox.prompt('请输入版本名称（可选）'")
  const restoreLockIndex = source.indexOf('beginOperation(`confirm-restore:${versionId}`)')
  const restoreDialogIndex = source.indexOf('ElMessageBox.confirm(', restoreLockIndex)
  const deleteLockIndex = source.indexOf('beginOperation(`confirm-delete:${versionId}`)')
  const deleteDialogIndex = source.indexOf('ElMessageBox.confirm(', deleteLockIndex)

  assert.ok(saveLockIndex > 0 && saveDialogIndex > saveLockIndex)
  assert.ok(restoreLockIndex > 0 && restoreDialogIndex > restoreLockIndex)
  assert.ok(deleteLockIndex > 0 && deleteDialogIndex > deleteLockIndex)
  assert.match(source, /function getListedVersionId\(item, \{ formalOnly = false \} = \{\}\)/)
  assert.match(source, /Number\.isSafeInteger\(id\)/)
  assert.match(source, /getListedVersionId\(item, \{ formalOnly: true \}\) !== versionId/)
  assert.match(source, /size="small"/)
  assert.match(source, /:disabled="isOperating \|\| isPreviewing"/)
  assert.doesNotMatch(source, /\n\s+small\n/)
})

test('failed preview restores the captured live tree instead of resuming over partial history data', () => {
  assert.match(source, /catch \(e\) \{[\s\S]*if \(isPreviewing\.value\) \{[\s\S]*await exitPreview\(\{ notify: false \}\)/)
  assert.match(source, /_previewSession = session/)
})

test('restore detail failure never reseeds collaboration with the stale local tree', () => {
  assert.doesNotMatch(source, /getData\(\)\?\.root/)
  assert.doesNotMatch(source, /emit\('yjs-reinit', currentRoot/)
  assert.match(source, /后端已经广播 document_reset/)
  assert.match(source, /restoreResponse\.data\?\.contentRevision/)
})

test('closing a delete confirmation is treated as cancellation', () => {
  assert.match(source, /e !== 'cancel' && e !== 'close'/)
})
