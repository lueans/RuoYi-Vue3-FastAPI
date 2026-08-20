import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { renderMindmapMarkdown } from '../mindmap-markdown.js'
import {
  renderMindmapMarkdownAst,
  renderMindmapPlainText,
} from '../mindmap-markdown-renderer.js'

test('脑图备注将常用 Markdown 渲染为受控语义标签', async () => {
  const html = await renderMindmapMarkdown([
    '# 会议结论',
    '',
    '- **完成** 数据拆分',
    '- 使用 `安全代码`',
    '',
    '> 保持兼容',
  ].join('\n'))

  assert.match(html, /<h1>会议结论<\/h1>/)
  assert.match(html, /<ul><li><p><strong>完成<\/strong> 数据拆分<\/p><\/li>/)
  assert.match(html, /<code>安全代码<\/code>/)
  assert.match(html, /<blockquote><p>保持兼容<\/p><\/blockquote>/)
})

test('脑图备注转义原始 HTML，危险链接只保留可见文本', async () => {
  const html = await renderMindmapMarkdown([
    '<script>globalThis.__mindmapXss = true</script>',
    '',
    '[危险链接](javascript:alert(1))',
  ].join('\n'))

  assert.doesNotMatch(html, /<script[\s>]/i)
  assert.match(html, /&lt;script&gt;globalThis\.__mindmapXss = true&lt;\/script&gt;/)
  assert.doesNotMatch(html, /href=/)
  assert.match(html, />危险链接</)
})

test('安全链接和图片具备新窗口隔离、来源保护和延迟加载属性', async () => {
  const html = await renderMindmapMarkdown([
    '[官网](https://example.com/docs)',
    '',
    '![示意图](https://example.com/image.png "图片标题")',
  ].join('\n'))

  assert.match(html, /href="https:\/\/example\.com\/docs"/)
  assert.match(html, /target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer"/)
  assert.match(html, /src="https:\/\/example\.com\/image\.png"/)
  assert.match(html, /alt="示意图" title="图片标题" loading="lazy" decoding="async" referrerpolicy="no-referrer"/)
})

test('引用链接复用定义，失效图片降级为转义后的替代文本', () => {
  const ast = {
    type: 'root',
    children: [
      {
        type: 'paragraph',
        children: [
          { type: 'linkReference', identifier: 'guide', children: [{ type: 'text', value: '指南' }] },
          { type: 'text', value: ' ' },
          { type: 'image', url: 'javascript:alert(1)', alt: '<封面>' },
        ],
      },
      { type: 'definition', identifier: 'guide', url: '/guide', title: '使用指南' },
    ],
  }
  const html = renderMindmapMarkdownAst(ast, {
    normalizeLink: value => value,
    normalizeImage: () => { throw new Error('unsafe') },
  })

  assert.match(html, /<a href="\/guide" title="使用指南"/)
  assert.match(html, /&lt;封面&gt;/)
  assert.doesNotMatch(html, /<img/)
})

test('纯文本降级路径不会执行标签并保留换行', () => {
  assert.equal(
    renderMindmapPlainText('第一行\n<img src=x onerror=alert(1)>'),
    '<p>第一行<br>&lt;img src=x onerror=alert(1)&gt;</p>',
  )
})

test('备注入口共享安全渲染器、竞态令牌、统一样式和输入上限', async () => {
  const componentRoot = new URL('../../components/MindMap/', import.meta.url)
  const [editor, noteEditor, hoverViewer, sidebarViewer, facade] = await Promise.all([
    readFile(new URL('Edit.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeNote.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeNoteContentShow.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeNoteSidebar.vue', componentRoot), 'utf8'),
    readFile(new URL('../mindmap-markdown.js', import.meta.url), 'utf8'),
  ])

  assert.match(editor, /import '\.\/styles\/markdown\.scss'/)
  assert.match(noteEditor, /:maxlength="MINDMAP_NOTE_MAX_LENGTH"/)
  assert.match(noteEditor, /show-word-limit/)
  assert.match(hoverViewer, /await renderMindmapMarkdown\(note\)/)
  assert.match(hoverViewer, /isCurrentNoteSession\(requestId, node, activeMindMap\)/)
  assert.match(hoverViewer, /componentAlive[\s\S]*currentMindMap === mindMap[\s\S]*props\.mindMap === mindMap/)
  assert.match(hoverViewer, /watch\(\(\) => props\.mindMap,[\s\S]*hideNote\(\)[\s\S]*attachContainer\(mindMap\)/)
  assert.match(hoverViewer, /catch \{[\s\S]*备注暂时无法显示/)
  assert.match(hoverViewer, /role="note"/)
  assert.match(hoverViewer, /scheduleHideNoteContent/)
  assert.match(hoverViewer, /safeLeft - elRect\.left/)
  assert.match(editor, /bus\.emit\('scheduleHideNoteContent', noteContentMindMap\)/)
  assert.match(sidebarViewer, /await renderMindmapMarkdown\(note\)/)
  assert.match(sidebarViewer, /isCurrentNoteSession\(requestId, node, activeMindMap\)/)
  assert.match(sidebarViewer, /store\.activeSidebar === 'noteSidebar'/)
  assert.match(sidebarViewer, /watch\(\(\) => store\.activeSidebar,[\s\S]*invalidateNoteSession\(\)/)
  assert.match(sidebarViewer, /componentAlive = false[\s\S]*invalidateNoteSession\(\)/)
  assert.match(sidebarViewer, /catch \{[\s\S]*备注暂时无法显示/)
  assert.doesNotMatch(hoverViewer + sidebarViewer, /function escapeHtml/)
  assert.match(facade, /import\('mdast-util-from-markdown'\)/)
})

test('备注编辑器提供安全预览、快捷保存并固定打开时的目标节点', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/NodeNote.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /<el-tab-pane label="编辑" name="edit">/)
  assert.match(source, /<el-tab-pane label="预览" name="preview">/)
  assert.match(source, /const previewSource = String\(note\.value\)/)
  assert.match(source, /await renderMindmapMarkdown\(previewSource\)/)
  assert.match(source, /requestId === previewRequestId[\s\S]*dialogVisible\.value[\s\S]*activeTab\.value === 'preview'/)
  assert.match(source, /catch \{[\s\S]*备注预览生成失败/)
  assert.match(source, /@keydown\.ctrl\.enter\.prevent="confirm"/)
  assert.match(source, /@keydown\.meta\.enter\.prevent="confirm"/)
  assert.match(source, /captureMindmapEditTargets\(activeNodes\.value, targetNode\)/)
  assert.match(source, /editTargets\.value\.forEach\(node =>/)
  assert.doesNotMatch(source, /const targets = appointNode/)
})

test('备注编辑器执行只读门禁并明确提示批量差异覆盖', async () => {
  const componentRoot = new URL('../../components/MindMap/', import.meta.url)
  const [noteEditor, toolbar] = await Promise.all([
    readFile(new URL('NodeNote.vue', componentRoot), 'utf8'),
    readFile(new URL('Toolbar.vue', componentRoot), 'utf8'),
  ])

  assert.match(noteEditor, /const isReadonly = computed\(\(\) => props\.readonly \|\| store\.isReadonly\)/)
  assert.match(noteEditor, /function handleShow\(targetNode = null\) \{\s*if \(isReadonly\.value\) return/)
  assert.match(noteEditor, /function confirm\(\) \{\s*if \(isReadonly\.value \|\| editTargets\.value\.length === 0\) return/)
  assert.match(noteEditor, /function removeNote\(\) \{\s*if \(isReadonly\.value \|\| editTargets\.value\.length === 0\) return/)
  assert.match(noteEditor, /watch\(isReadonly,[\s\S]*dialogVisible\.value = false/)
  assert.match(noteEditor, /:type="hasMixedNotes \? 'warning' : 'info'"/)
  assert.match(noteEditor, /备注内容不同，保存后会用当前内容覆盖全部/)
  assert.match(toolbar, /<NodeNote :readonly="isReadonly"/)
  assert.match(toolbar, /function onNodeNoteDblclick\(node, e, _noteElement, sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource\(sourceMindMap, store\.mindMap\)[\s\S]*if \(isReadonly\.value\) return/)
})
