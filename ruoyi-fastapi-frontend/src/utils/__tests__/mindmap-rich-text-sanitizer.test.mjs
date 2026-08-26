import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  sanitizeRichTextHtml,
  sanitizeRichTextStyle,
} from '../../libs/simple-mind-map/src/utils/richText.js'

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../..',
)

test('富文本净化器在无 DOM 环境中按纯文本转义并保持失败关闭', () => {
  const sanitized = sanitizeRichTextHtml(
    '<img src=x onerror="alert(1)"><script>alert(2)</script><p>安全文本</p>',
  )

  assert.doesNotMatch(sanitized, /<(?:img|script|p)\b/i)
  assert.match(sanitized, /&lt;img/)
  assert.match(sanitized, /安全文本/)
})

test('富文本内联样式只保留 Quill 所需的安全属性和值', () => {
  assert.equal(
    sanitizeRichTextStyle([
      'color: #ff0000',
      'font-size: 18px',
      'font-family: "Microsoft YaHei", sans-serif',
      'background-image: url(javascript:alert(1))',
      'position: fixed',
      'color: expression(alert(1))',
    ].join(';')),
    'color: #ff0000; font-size: 18px; font-family: "Microsoft YaHei", sans-serif',
  )
})

test('节点渲染、富文本编辑和通用 DOM 工具共用统一净化边界', async () => {
  const [
    nodeRenderer,
    richTextPlugin,
    utils,
    search,
    comments,
    outerFrameText,
    associativeLineText,
  ] = await Promise.all([
    readFile(path.join(
      frontendRoot,
      'src/libs/simple-mind-map/src/core/render/node/nodeCreateContents.js',
    ), 'utf8'),
    readFile(path.join(
      frontendRoot,
      'src/libs/simple-mind-map/src/plugins/RichText.js',
    ), 'utf8'),
    readFile(path.join(
      frontendRoot,
      'src/libs/simple-mind-map/src/utils/index.js',
    ), 'utf8'),
    readFile(path.join(frontendRoot, 'src/components/MindMap/Search.vue'), 'utf8'),
    readFile(path.join(frontendRoot, 'src/components/MindMap/CommentSidebar.vue'), 'utf8'),
    readFile(path.join(
      frontendRoot,
      'src/libs/simple-mind-map/src/plugins/outerFrame/outerFrameText.js',
    ), 'utf8'),
    readFile(path.join(
      frontendRoot,
      'src/libs/simple-mind-map/src/plugins/associativeLine/associativeLineText.js',
    ), 'utf8'),
  ])

  assert.match(nodeRenderer, /sanitizeRichTextHtml\(text\)/)
  assert.match(richTextPlugin, /innerHTML = sanitizeRichTextHtml\(/)
  assert.match(richTextPlugin, /return sanitizeRichTextHtml\(/)
  assert.match(utils, /getTextFromHtmlEl\.innerHTML = sanitizeRichTextHtml\(html\)/)
  assert.match(utils, /nodeRichTextToTextWithWrapEl\.innerHTML = sanitizeRichTextHtml\(html\)/)
  assert.doesNotMatch(search, /template\.innerHTML = (?:rawText|name)/)
  assert.match(comments, /getTextFromHtml\(String\(value\)\)/)
  assert.match(outerFrameText, /\.map\(htmlEscape\)/)
  assert.match(associativeLineText, /\.map\(htmlEscape\)/)
})
