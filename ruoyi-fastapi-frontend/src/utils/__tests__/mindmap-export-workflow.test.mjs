import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  normalizeMindmapExportPadding,
  normalizeMindmapExportRuntimeConfig,
  validateMindmapExportName,
} from '../mindmap-export.js'

test('export names are trimmed and do not duplicate the selected extension', () => {
  assert.deepEqual(validateMindmapExportName('  项目规划.pdf  ', 'pdf'), {
    name: '项目规划',
    error: '',
  })
  assert.deepEqual(validateMindmapExportName('脑图.XMIND', 'xmind'), {
    name: '脑图',
    error: '',
  })
})

test('export names reject empty, path-like, reserved and trailing characters', () => {
  assert.match(validateMindmapExportName('  ', 'png').error, /请输入/)
  assert.match(validateMindmapExportName('../secret', 'png').error, /保留字符/)
  assert.match(validateMindmapExportName('CON', 'png').error, /保留字符/)
  assert.match(validateMindmapExportName('report.', 'png').error, /句点结尾/)
  assert.match(validateMindmapExportName('a'.repeat(121), 'png').error, /120/)
})

test('export padding is finite, integral and clamped to the UI range', () => {
  assert.equal(normalizeMindmapExportPadding('12.6'), 13)
  assert.equal(normalizeMindmapExportPadding(-4), 0)
  assert.equal(normalizeMindmapExportPadding(999), 200)
  assert.equal(normalizeMindmapExportPadding('invalid'), 10)
})

test('export runtime config only accepts bounded padding and a callable footer', () => {
  assert.deepEqual(normalizeMindmapExportRuntimeConfig({
    exportPaddingX: -10,
    exportPaddingY: 999,
    addContentToFooter: 'unsafe',
  }), {
    exportPaddingX: 0,
    exportPaddingY: 200,
    addContentToFooter: null,
  })
  const footer = () => '项目脑图'
  assert.equal(normalizeMindmapExportRuntimeConfig({ addContentToFooter: footer }).addContentToFooter, footer)
})

test('export dialog uses semantic controls and awaits one request lifecycle', async () => {
  const source = await readFile(new URL('../../components/MindMap/Export.vue', import.meta.url), 'utf8')

  assert.match(source, /class="xmindExportShell"/)
  assert.match(source, /class="exportPreviewPane"/)
  assert.match(source, /class="exportSettingsPane"/)
  assert.match(source, /aria-label="导出格式"/)
  assert.match(source, /导出为\{\{ currentTypeData\?\.name/)
  assert.match(source, /store\.mindMap\.getSvgData\(\{/)
  assert.match(source, /setAttribute\('viewBox', `0 0 \$\{rect\.width\} \$\{rect\.height\}`\)/)
  assert.match(source, /const isExporting = ref\(false\)/)
  assert.match(source, /await requestExport\(createExportArgs\(type, name, footerText\)\)/)
  assert.match(source, /config: \{[\s\S]*exportPaddingX: paddingX\.value[\s\S]*addContentToFooter:/)
  assert.match(source, /role="status" aria-live="polite"/)
})

test('export footer state is explicitly cleared and failures keep the dialog open', async () => {
  const source = await readFile(new URL('../../components/MindMap/Export.vue', import.meta.url), 'utf8')

  assert.equal(source.includes("bus.emit('paddingChange'"), false)
  assert.match(source, /addContentToFooter: footerText \? \(\) => footerText : null/)
  assert.match(source, /dialogVisible\.value = false\s*\} catch \(error\)/)
  assert.match(source, /exportStatusText\.value = error\?\.message \|\| '导出失败，请重试'/)
})

test('editor resolves export requests only after the plugin generates a file', async () => {
  const [editorSource, mindMapSource, eventBusSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/index.js', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/useEventBus.js', import.meta.url), 'utf8'),
  ])

  assert.match(editorSource, /bus\.on\('exportRequest', onExportRequest\)/)
  assert.match(editorSource, /const activeMindMap = mindMap\.value/)
  assert.match(editorSource, /await ensureExportPlugins\(activeMindMap, type\)/)
  assert.match(editorSource, /sessionCancelled\(signal\) \|\| activeMindMap !== mindMap\.value/)
  assert.match(editorSource, /activeMindMap\.updateConfig\(runtimeConfig\)/)
  assert.match(editorSource, /activeMindMap\.updateConfig\(previousConfig\)/)
  assert.match(editorSource, /if \(!result\) throw new Error\('导出组件未生成文件'\)/)
  assert.match(editorSource, /request\.reject\?\.\(error\)/)
  assert.match(mindMapSource, /errorHandler\(ERROR_TYPES\.EXPORT_ERROR, error\)\s*throw error/)
  assert.match(eventBusSource, /if \(!eventListeners\?\.length\) return false/)
  assert.match(eventBusSource, /eventListeners\.slice\(\)\.forEach/)
  assert.match(eventBusSource, /return true/)
})
