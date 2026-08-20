import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MINDMAP_PREVIEW_FEATURES,
  detectMindmapDocumentFeatures,
  detectMindmapPreviewFeatures,
} from '../mindmap-preview.js'

test('普通只读脑图不加载编辑、导出或复杂渲染插件', () => {
  const features = detectMindmapPreviewFeatures({
    layout: 'logicalStructure',
    root: { data: { uid: 'root', text: '中心主题' }, children: [] },
  })

  assert.deepEqual(features, [])
})

test('预览插件只根据实际文档能力按需加载', () => {
  const features = detectMindmapPreviewFeatures({
    layout: 'mindMap',
    root: {
      data: {
        uid: 'root',
        text: '<span class="ql-formula" data-value="x^2"></span>',
        richText: true,
        associativeLineTargets: ['child'],
      },
      children: [{
        data: { uid: 'child', text: '分支', outerFrame: { groupId: 'frame-1' } },
        children: [],
      }],
    },
  })

  assert.deepEqual(features, [
    MINDMAP_PREVIEW_FEATURES.associativeLine,
    MINDMAP_PREVIEW_FEATURES.formula,
    MINDMAP_PREVIEW_FEATURES.mindMapLayoutPro,
    MINDMAP_PREVIEW_FEATURES.outerFrame,
  ])
})

test('异常循环对象不会让预览能力扫描无限递归', () => {
  const root = { data: { uid: 'root' }, children: [] }
  root.children.push(root)

  assert.deepEqual(detectMindmapPreviewFeatures({ root }), [])
})

test('编辑器能力扫描识别概要等嵌套扩展数据中的公式', () => {
  const root = {
    data: {
      uid: 'root',
      generalization: [{
        text: '<span class="ql-formula" data-value="a+b"></span>',
        richText: true,
      }],
    },
    children: [],
  }

  assert.deepEqual(detectMindmapDocumentFeatures({ root }), [MINDMAP_PREVIEW_FEATURES.formula])
})

test('公开预览加载器不允许静态引入编辑和导出插件', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/usePreviewPlugins.js', import.meta.url),
    'utf8',
  )
  const forbiddenPlugins = [
    'Export.js', 'ExportPDF.js', 'ExportXMind.js', 'Painter.js',
    'Select.js', 'Search.js', 'NodeImgAdjust.js', 'Demonstrate.js',
  ]

  for (const plugin of forbiddenPlugins) {
    assert.equal(source.includes(plugin), false, `公开预览不应加载 ${plugin}`)
  }
})
