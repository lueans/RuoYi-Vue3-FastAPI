import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const editorUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const pageUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const apiUrl = new URL('../../api/mindmap/mindmap.js', import.meta.url)
const requestUrl = new URL('../request.js', import.meta.url)

test('页面只在画布、插件和事件生命周期完成后进入就绪态', async () => {
  const [editorSource, pageSource] = await Promise.all([
    readFile(editorUrl, 'utf8'),
    readFile(pageUrl, 'utf8'),
  ])
  const mountedBlock = editorSource.match(/onMounted\(async \(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''

  assert.ok(mountedBlock.indexOf('bindBusEvents()') < mountedBlock.indexOf("emit('ready')"))
  assert.match(editorSource, /await waitForMindmapInitialRender\(mm\)/)
  assert.match(editorSource, /await waitForMindmapInitialRender\(mm\)[\s\S]*?establishMindmapInitialHistoryBaseline\(mm\)[\s\S]*?initialRenderReady = true[\s\S]*?startYjsSyncIfReady\(\)/)
  assert.match(editorSource, /function startYjsSyncIfReady[\s\S]*?!initialRenderReady/)
  assert.match(editorSource, /import \{[\s\S]*?establishMindmapInitialHistoryBaseline,[\s\S]*?waitForMindmapInitialRender,[\s\S]*?\} from '@\/utils\/mindmap-initial-render'/)
  assert.match(editorSource, /function onMindmapDataChangeDetail\(detailList\) \{\s*if \(!initialRenderReady\) return/)
  assert.match(editorSource, /function onBusDataChange\(data, sourceMindMap = null\) \{[\s\S]*?if \(!initialRenderReady\) return/)
  assert.match(mountedBlock, /catch \(error\) \{[\s\S]*?sessionCancelled\(sessionController\?\.signal\)[\s\S]*?emit\('load-error'/)
  assert.ok(
    mountedBlock.indexOf('sessionCancelled(sessionController?.signal)')
      < mountedBlock.indexOf("console.error('脑图编辑器初始化失败:'"),
  )
  assert.match(editorSource, /if \(!container\) \{[\s\S]*?emit\('load-error'/)
  assert.match(pageSource, /@ready="onEditorReady"/)
  assert.match(pageSource, /:key="editorInstanceKey"/)
  assert.match(pageSource, /role="status"[\s\S]*?aria-busy="true"/)
  assert.match(pageSource, /const documentLoaded = computed\(\(\) => \([\s\S]*?editorReady\.value/)
  assert.match(pageSource, /documentLoaded && !isZenMode && !isReadonly/)
  assert.match(pageSource, /watch\(editorSessionKey, \(\) => \{[\s\S]*?editorReady\.value = false/)
  assert.match(pageSource, /重新加载/)
  assert.match(pageSource, /function retryEditorLoad\(\) \{[\s\S]*?serverCanEdit\.value = null[\s\S]*?loadError\.value = ''[\s\S]*?editorRetryNonce\.value \+= 1/)
})

test('服务端缺省主题使用默认值而不会让新建脑图加载失败', async () => {
  const editorSource = await readFile(editorUrl, 'utf8')

  assert.match(
    editorSource,
    /function normalizeServerTheme\(theme\) \{[\s\S]*?if \(theme == null\) return \{ template: 'default', config: \{\} \}[\s\S]*?normalizeMindmapDocumentMetaPatch\(\{ theme \}\)/,
  )
  assert.match(
    editorSource,
    /const normalizedTheme = normalizeServerTheme\(data\.theme\)[\s\S]*?themeTemplate = normalizedTheme\.template/,
  )
})

test('快速切换会取消旧详情请求并关闭所属草稿确认', async () => {
  const [editorSource, apiSource, requestSource] = await Promise.all([
    readFile(editorUrl, 'utf8'),
    readFile(apiUrl, 'utf8'),
    readFile(requestUrl, 'utf8'),
  ])

  assert.match(apiSource, /getMindmap\(mindmapId, \{ signal, silentError = false \} = \{\}\)/)
  assert.match(apiSource, /method: 'get',[\s\S]*?signal,/)
  assert.match(editorSource, /sessionController = new AbortController\(\)/)
  assert.match(editorSource, /getMindmap\(props\.mindmapId, \{ signal \}\)/)
  assert.match(editorSource, /if \(sessionCancelled\(signal\)\) return/)
  assert.match(editorSource, /sessionController\?\.abort\(\)/)
  assert.match(editorSource, /if \(localDraftDialogOpen \|\| conflictDialogOpen\) ElMessageBox\.close\(\)/)
  assert.match(editorSource, /finally \{\s*localDraftDialogOpen = false/)
  assert.match(requestSource, /if \(axios\.isCancel\(error\) \|\| error\?\.code === 'ERR_CANCELED'\) \{\s*return Promise\.reject\(error\)/)
  assert.match(requestSource, /const returnPath = getCurrentLoginReturnPath\(location\)/)
  assert.match(requestSource, /location\.href = returnPath/)
  assert.doesNotMatch(requestSource, /location\.href = ['"]\/index['"]/)
})

test('运行期协作重载和冲突处理也服从当前会话取消边界', async () => {
  const editorSource = await readFile(editorUrl, 'utf8')
  const reloadBlock = editorSource.match(/async function reloadLatestServerDocument[\s\S]*?\n\}/)?.[0] || ''
  const conflictEntryBlock = editorSource.match(/async function resolveContentConflict[\s\S]*?\n\}/)?.[0] || ''
  const conflictBlock = editorSource.match(/async function performContentConflictResolution[\s\S]*?\n\}/)?.[0] || ''

  assert.match(reloadBlock, /const signal = sessionController\?\.signal/)
  assert.match(reloadBlock, /getMindmap\(props\.mindmapId, \{[\s\S]*?signal,[\s\S]*?silentError: requireClean/)
  assert.match(reloadBlock, /if \(sessionCancelled\(signal\) \|\| !mindMap\.value\) return false/)
  assert.match(reloadBlock, /return true/)
  assert.match(conflictEntryBlock, /if \(conflictResolutionPromise\) return conflictResolutionPromise/)
  assert.match(conflictEntryBlock, /conflictResolutionPromise = operation/)
  assert.match(conflictEntryBlock, /conflictResolutionPromise === operation/)
  assert.equal(
    (conflictEntryBlock.match(/conflictResolutionPromise === operation/g) || []).length,
    1,
  )
  assert.match(conflictBlock, /conflictDialogOpen = true/)
  assert.match(conflictBlock, /finally \{\s*conflictDialogOpen = false/)
  assert.match(conflictBlock, /recoverFromSaveRevisionConflict\(conflictData, localFullData\)/)
  assert.doesNotMatch(conflictBlock, /downloadConflictBackup/)
  assert.match(conflictBlock, /if \(sessionCancelled\(signal\)\) return false/)
  assert.match(editorSource, /if \(localDraftDialogOpen \|\| conflictDialogOpen\) ElMessageBox\.close\(\)/)
  assert.match(editorSource, /const reloaded = authoritativeReloadRequired[\s\S]*?reloadLatestServerDocument\(\)[\s\S]*?if \(!reloaded\) return/)
  assert.match(editorSource, /const reloaded = await reloadLatestServerDocument\(\{[\s\S]*?preserveLocalDraft: false,[\s\S]*?expectedDraftChangeVersion:[\s\S]*?if \(!reloaded\)/)
})

test('会话终止会关闭异步工作且忽略迟到的保存响应', async () => {
  const editorSource = await readFile(editorUrl, 'utf8')
  const cancelBlock = editorSource.match(/function cancelSessionAsyncWork[\s\S]*?\n\}/)?.[0] || ''
  const terminationBlock = editorSource.match(/function terminateEditingSession[\s\S]*?\n\}/)?.[0] || ''
  const saveBlock = editorSource.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''

  assert.match(cancelBlock, /sessionController\?\.abort\(\)/)
  assert.match(cancelBlock, /ElMessageBox\.close\(\)/)
  assert.ok(
    terminationBlock.indexOf('terminalState = eventName')
      < terminationBlock.indexOf('cancelSessionAsyncWork()'),
  )
  assert.match(saveBlock, /await submitMindmapSaveMutation[\s\S]*?batchUpdateMindmapContent[\s\S]*?if \(sessionCancelled\(sessionController\?\.signal\) \|\| !mindMap\.value\) return false/)
})
