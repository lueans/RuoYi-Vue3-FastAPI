import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyMindmapDocumentConfig,
  getMindmapDocumentConfig,
  getMindmapLocalRuntimeConfig,
  normalizeMindmapDocumentData,
  normalizeWatermarkConfig,
  updateMindmapDocumentConfig,
} from '../mindmap-document-config.js'

test('文档设置保留 simple-mind-map 未知扩展数据并限制已知数值', () => {
  const source = {
    pluginState: { future: true },
    simpleMindMap: { future: { enabled: true }, config: { futureOption: 7 } },
  }
  const result = updateMindmapDocumentConfig(source, {
    imgTextMargin: 999,
    textContentMargin: -4,
  })

  assert.deepEqual(result.pluginState, { future: true })
  assert.deepEqual(result.simpleMindMap.future, { enabled: true })
  assert.equal(result.simpleMindMap.config.futureOption, 7)
  assert.equal(result.simpleMindMap.config.imgTextMargin, 50)
  assert.equal(result.simpleMindMap.config.textContentMargin, 0)
  assert.equal(source.simpleMindMap.config.imgTextMargin, undefined)
})

test('水印设置有稳定默认值、长度和安全数值边界', () => {
  assert.deepEqual(normalizeWatermarkConfig({ text: '' }), { text: '' })
  const value = normalizeWatermarkConfig({
    text: 'x'.repeat(250), onlyExport: 1, angle: 200,
    lineSpacing: 1, textSpacing: 1000,
    textStyle: { color: 'red', fontSize: 200 },
  })
  assert.equal(value.text.length, 200)
  assert.equal(value.onlyExport, false)
  assert.equal(value.angle, 90)
  assert.equal(value.lineSpacing, 20)
  assert.equal(value.textSpacing, 400)
  assert.deepEqual(value.textStyle, { color: 'red', fontSize: 60 })
})

test('读取和应用设置只向运行时传递受支持的展示配置', () => {
  const documentData = updateMindmapDocumentConfig({}, {
    watermarkConfig: { text: '机密', onlyExport: true },
    imgTextMargin: 12,
    textContentMargin: 6,
  })
  const calls = []
  const mindMap = {
    updateConfig: value => calls.push(['config', value]),
    reRender: () => calls.push(['render']),
    watermark: { updateWatermark: value => calls.push(['watermark', value]) },
  }

  const config = applyMindmapDocumentConfig(mindMap, documentData)

  assert.deepEqual(getMindmapDocumentConfig(documentData), config)
  assert.deepEqual(calls[0], ['config', { imgTextMargin: 12, textContentMargin: 6 }])
  assert.equal(calls[1][0], 'watermark')
  assert.deepEqual(calls[2], ['render'])
})

test('旧版 localStorage 中的文档设置不会泄漏到其他脑图', () => {
  const localConfig = getMindmapLocalRuntimeConfig({
    openPerformance: true,
    watermarkConfig: { text: '旧水印' },
    imgTextMargin: 20,
    textContentMargin: 10,
  })

  assert.deepEqual(localConfig, { openPerformance: true })
  const calls = []
  applyMindmapDocumentConfig({
    updateConfig: value => calls.push(value),
    watermark: { updateWatermark: value => calls.push(value) },
    reRender() {},
  }, {})
  assert.deepEqual(calls, [
    { imgTextMargin: 5, textContentMargin: 2 },
    { text: '' },
  ])
})

test('重复应用相同文档设置不会重建节点或清空连续录入选区', () => {
  const calls = []
  const current = { imgTextMargin: 12, textContentMargin: 6 }
  const documentData = updateMindmapDocumentConfig({}, current)
  const mindMap = {
    getConfig: key => current[key],
    updateConfig: value => calls.push(['config', value]),
    reRender: () => calls.push(['render']),
    watermark: { updateWatermark: value => calls.push(['watermark', value]) },
  }

  applyMindmapDocumentConfig(mindMap, documentData)

  assert.deepEqual(calls.map(call => call[0]), ['config', 'watermark'])
})

test('规范化文档扩展数据不会保留原对象引用或危险原型键', () => {
  const source = JSON.parse('{"safe":{"value":1},"__proto__":{"polluted":true}}')
  const normalized = normalizeMindmapDocumentData(source)
  source.safe.value = 2

  assert.deepEqual(normalized.safe, { value: 1 })
  assert.equal(Object.prototype.polluted, undefined)
  assert.equal(Object.prototype.hasOwnProperty.call(normalized, '__proto__'), false)
})

test('存量深层插件配置不会在前端规范化时被静默截断', () => {
  const source = { plugin: {} }
  let cursor = source.plugin
  for (let index = 0; index < 30; index += 1) {
    cursor.next = {}
    cursor = cursor.next
  }
  cursor.value = '仍然保留'

  const normalized = normalizeMindmapDocumentData(source)
  cursor = normalized.plugin
  for (let index = 0; index < 30; index += 1) cursor = cursor.next

  assert.equal(cursor.value, '仍然保留')
})
