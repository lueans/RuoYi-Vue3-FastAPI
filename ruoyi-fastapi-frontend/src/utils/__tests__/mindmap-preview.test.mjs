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

test('新会话预览按文档内容加载富文本样式和可见水印', () => {
  const features = detectMindmapPreviewFeatures({
    root: {
      data: {
        uid: 'root',
        text: '<p><span>富文本主题</span></p>',
        richText: true,
      },
      children: [],
    },
    documentData: {
      simpleMindMap: {
        config: {
          watermarkConfig: { text: '内部资料', onlyExport: false },
        },
      },
    },
  })

  assert.deepEqual(features, [
    MINDMAP_PREVIEW_FEATURES.richText,
    MINDMAP_PREVIEW_FEATURES.watermark,
  ])
})

test('仅导出水印不会进入只读预览运行时', () => {
  const features = detectMindmapPreviewFeatures({
    root: { data: { uid: 'root', text: '中心主题' }, children: [] },
    documentData: {
      simpleMindMap: {
        config: {
          watermarkConfig: { text: '导出水印', onlyExport: true },
        },
      },
    },
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
    MINDMAP_PREVIEW_FEATURES.richText,
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

  assert.deepEqual(detectMindmapDocumentFeatures({ root }), [
    MINDMAP_PREVIEW_FEATURES.formula,
    MINDMAP_PREVIEW_FEATURES.richText,
  ])
})

test('公开预览加载器不允许静态引入编辑和导出插件', async () => {
  const [source, loaderSource, viewerSource, richTextSource, styleSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/usePreviewPlugins.js', import.meta.url), 'utf8'),
    readFile(new URL('../mindmap-plugin-loader.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/plugins/RichTextViewer.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/plugins/RichText.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/plugins/RichTextStyle.js', import.meta.url), 'utf8'),
  ])
  const forbiddenPlugins = [
    'Export.js', 'ExportPDF.js', 'ExportXMind.js', 'Painter.js',
    'Select.js', 'Search.js', 'NodeImgAdjust.js', 'Demonstrate.js',
  ]

  for (const plugin of forbiddenPlugins) {
    assert.equal(source.includes(plugin), false, `公开预览不应加载 ${plugin}`)
  }
  assert.match(loaderSource, /plugins\/RichTextViewer\.js/)
  assert.doesNotMatch(loaderSource, /plugins\/RichText\.js/)
  assert.match(viewerSource, /appendCss\(STYLE_KEY, RICH_TEXT_NODE_CSS\)/)
  assert.doesNotMatch(viewerSource, /handleDataToRichText|clearHistory|addHistory|render\(/)
  assert.match(richTextSource, /appendCss\('richText', RICH_TEXT_NODE_CSS\)/)
  assert.match(styleSource, /\.smm-richtext-node-wrap p,[\s\S]*?margin: 0;[\s\S]*?padding: 0;/)
})
