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

test('import dialog exposes one loading state and blocks duplicate submissions', () => {
  assert.match(toolbarSource, /<ImportDialog ref="importRef" :readonly="isReadonly"/)
  assert.match(source, /readonly: \{ type: Boolean, default: false \}/)
  assert.match(source, /const isImporting = ref\(false\)/)
  assert.match(source, /:loading="isImporting"/)
  assert.match(source, /:disabled="isImporting \|\| readonly"/)
  assert.match(source, /if \(isImporting\.value\) \{[\s\S]*已有文件正在导入/)
  assert.match(source, /finally \{\s*if \(requestId === importRequestId\) isImporting\.value = false\s*\}/)
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

test('failed imports keep the dialog open while successful imports close it', () => {
  assert.match(source, /const imported = await executeImport\(file, type\)/)
  assert.match(source, /if \(imported\) \{\s*dialogVisible\.value = false/)
  assert.match(source, /catch \(error\) \{[\s\S]*return false[\s\S]*finally/)
})

test('multi-canvas XMind selection has explicit settle and cancellation paths', () => {
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
