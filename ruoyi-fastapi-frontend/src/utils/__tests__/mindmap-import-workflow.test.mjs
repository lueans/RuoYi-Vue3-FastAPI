import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(
  new URL('../../components/MindMap/Import.vue', import.meta.url),
  'utf8'
)
const toolbarSource = await readFile(
  new URL('../../components/MindMap/Toolbar.vue', import.meta.url),
  'utf8'
)

test('import opens the native picker directly and blocks duplicate submissions', () => {
  assert.match(toolbarSource, /<ImportDialog ref="importRef" :readonly="isReadonly"/)
  assert.match(toolbarSource, /const importFormatHint = '支持 \.xmind、\.smm、\.json、\.md 文件'/)
  assert.equal((toolbarSource.match(/:content="importFormatHint"/g) || []).length, 2)
  assert.equal((toolbarSource.match(/:aria-label="`导入文件，\$\{importFormatHint\}`"/g) || []).length, 2)
  assert.match(toolbarSource, /const importFormatSummary = '\.xmind · \.smm · \.json · \.md'/)
  assert.match(toolbarSource, /class="importFormatHint">\{\{ importFormatSummary \}\}/)
  assert.match(source, /readonly: \{ type: Boolean, default: false \}/)
  assert.match(source, /<input[\s\S]*ref="fileInputRef"[\s\S]*type="file"/)
  assert.match(source, /:accept="supportFileStr"/)
  assert.match(source, /@change="handleFileInputChange"/)
  assert.match(source, /fileInputRef\.value\?\.click\(\)/)
  assert.match(source, /input\.value = ''/)
  assert.match(source, /const supportFileStr = '\.xmind,\.smm,\.json,\.md'/)
  assert.match(source, /请选择 XMind、SMM、JSON 或 Markdown 文件/)
  assert.doesNotMatch(source, /class="nodeImportDialog"/)
  assert.match(source, /const isImporting = ref\(false\)/)
  assert.match(source, /:disabled="isImporting \|\| readonly"/)
  assert.match(source, /if \(isImporting\.value\) \{[\s\S]*已有文件正在导入/)
  assert.match(source, /finally \{[\s\S]*progressMessage\.close\(\)[\s\S]*if \(requestId === importRequestId\) isImporting\.value = false\s*\}/)
  assert.match(source, /role="status" aria-live="polite"/)
})

test('all supported formats flow through one validation and canvas update boundary', () => {
  assert.match(source, /async function executeImport\(file, type\)/)
  assert.match(source, /const requestId = \+\+importRequestId/)
  assert.match(source, /type === 'smm' \|\| type === 'json'/)
  assert.match(source, /type === 'xmind'/)
  assert.match(source, /type === 'md'/)
  assert.match(source, /assertMindmapImportDocument\(data\)/)
  assert.equal((source.match(/bus\.emit\('setData', data, \{ resolve, reject \}\)/g) || []).length, 1)
  assert.match(source, /await new Promise\(\(resolve, reject\) => \{/)
  assert.equal((source.match(/if \(!isImportRequestCurrent\(requestId\)\) return false/g) || []).length >= 3, true)
  assert.match(source, /if \(!handled\) reject\(new Error\('脑图编辑器尚未就绪'\)\)/)
})

test('failed imports keep the picker reusable while successful imports close the active sidebar', () => {
  assert.match(source, /const imported = await executeImport\(\{ raw: file, name \}, type\)/)
  assert.match(source, /if \(imported\) actions\.setActiveSidebar\(null\)/)
  assert.match(source, /input\.value = ''/)
  assert.match(source, /catch \(error\) \{[\s\S]*return false[\s\S]*finally/)
})

test('multi-canvas XMind selection has explicit settle and cancellation paths', () => {
  assert.match(source, /class="canvasSelectShell"/)
  assert.match(source, /class="canvasOption"/)
  assert.match(source, /modal-class="xmindCanvasSelectOverlay"/)
  assert.match(source, /:close-on-click-modal="false"/)
  assert.match(source, /:close-on-press-escape="false"/)
  assert.match(source, /@click="cancelSelect"/)
  assert.match(source, /selectPromiseReject = reject/)
  assert.match(source, /error\.code = 'IMPORT_CANCELLED'/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*invalidateImportSession\('导入组件已卸载'\)/)
})

test('URL imports are same-origin, abortable and reject oversized responses early', () => {
  assert.match(source, /url\.origin !== window\.location\.origin/)
  assert.match(source, /new AbortController\(\)/)
  assert.match(source, /fetch\(url\.href, \{ signal: requestController\.signal \}\)/)
  assert.match(source, /res\.headers\.get\('content-length'\)/)
  assert.match(source, /fileFetchController\?\.abort\(\)/)
  assert.match(source, /watch\(\(\) => props\.readonly[\s\S]*invalidateImportSession/)
  assert.match(source, /componentAlive = false[\s\S]*invalidateImportSession\('导入组件已卸载'\)/)
})
