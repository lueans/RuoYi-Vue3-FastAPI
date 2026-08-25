import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const toolbarSourceUrl = new URL('../../components/MindMap/Toolbar.vue', import.meta.url)
const editorPageSourceUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const editorSourceUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const scaleSourceUrl = new URL('../../components/MindMap/Scale.vue', import.meta.url)
const fullscreenSourceUrl = new URL('../../components/MindMap/Fullscreen.vue', import.meta.url)
const demonstrateSourceUrl = new URL('../../components/MindMap/Demonstrate.vue', import.meta.url)

test('编辑器工具栏操作使用可聚焦按钮而不是点击 div', async () => {
  const source = await readFile(toolbarSourceUrl, 'utf8')

  assert.equal(/<div[^>]*class="toolbarBtn"/.test(source), false)
  assert.match(source, /<button[\s\S]*type="button"[\s\S]*class="toolbarBtn"/)
  assert.match(source, /:disabled="isButtonDisabled\(item\)"/)
  assert.match(source, /:aria-pressed="item === 'painter' \? isInPainter : undefined"/)
})

test('横向和溢出工具栏复用同一动作定义与禁用规则', async () => {
  const source = await readFile(toolbarSourceUrl, 'utf8')

  assert.match(source, /const toolbarItemDefinitions = Object\.freeze/)
  assert.equal((source.match(/@click="executeToolbarItem\(item\)"/g) || []).length, 2)
  assert.equal((source.match(/isButtonDisabled\(item\)/g) || []).length >= 4, true)
  assert.match(source, /if \(isButtonDisabled\(item\)\) return/)
})

test('顶部工具栏公开操作分组与溢出展开状态', async () => {
  const source = await readFile(toolbarSourceUrl, 'utf8')

  assert.match(source, /role="toolbar" aria-label="脑图编辑操作"/)
  assert.match(source, /role="group" aria-label="节点操作"/)
  assert.match(source, /role="group" aria-label="文件操作"/)
  assert.match(source, /aria-controls="mindmap-toolbar-overflow"/)
  assert.match(source, /:aria-expanded="popoverShow"/)
  assert.match(source, /id="mindmap-toolbar-overflow"[\s\S]*aria-label="更多节点操作"/)
  assert.match(source, /const defaultBtnList = \[\s*'siblingNode',\s*'childNode',\s*'associativeLine',\s*'summary',\s*'outerFrame',\s*'image',\s*'back',\s*'forward'/)
  assert.match(source, /dividerBefore: index > 0 && \['back', 'painter'\]\.includes\(item\)/)
  assert.match(source, /props\.embedded \? '2px' : '20px'/)
  assert.match(source, /const maxVisibleCount = props\.embedded \? Math\.min\(8, all\.length\) : all\.length/)
  assert.match(source, /v-if="props\.embedded" class="overflowFileOperations"/)
  assert.match(source, /v-if="!props\.embedded" class="toolbarBlock" role="group" aria-label="文件操作"/)
})

test('编辑命令以内嵌模式进入单层工作台并在窄屏提供可访问命令面板', async () => {
  const [toolbar, editorPage, editor] = await Promise.all([
    readFile(toolbarSourceUrl, 'utf8'),
    readFile(editorPageSourceUrl, 'utf8'),
    readFile(editorSourceUrl, 'utf8'),
  ])

  assert.match(editorPage, /<Toolbar embedded class="header-command-toolbar" \/>/)
  assert.match(editorPage, /class="header-utility-group" aria-label="文档工具"/)
  assert.match(editorPage, /class="header-action-label">搜索<\/span>/)
  assert.match(editorPage, /class="header-action-label">历史<\/span>/)
  assert.match(editorPage, /class="header-action-label">协作<\/span>/)
  assert.match(editorPage, /class="brand-mark" aria-hidden="true"/)
  assert.match(editorPage, /aria-label="返回脑图列表"[\s\S]*?<ArrowLeft \/>/)
  assert.match(editorPage, /<span>我的脑图<\/span>/)
  assert.match(editorPage, /:aria-label="activeSidebar === 'outline' \? '关闭脑图大纲' : '打开脑图大纲'"/)
  assert.match(editorPage, /:aria-pressed="activeSidebar === 'outline'"[\s\S]*?@click="openOutline"/)
  assert.match(editorPage, /class="readonly-canvas-context" aria-label="脑图文档摘要"/)
  assert.match(editorPage, /\{\{ documentNodeCount \}\} 个节点 · \{\{ documentVersionCount \}\} 个版本/)
  assert.match(editorPage, /class="readonly-mode-banner" role="group" aria-label="阅读模式"/)
  assert.match(editorPage, /v-if="canEnterEditMode" type="button" @click="enterEditMode">进入编辑<\/button>/)
  assert.match(editorPage, /function enterEditMode\(\) \{[\s\S]*?delete query\.readonly[\s\S]*?router\.push\(\{ path: route\.path, query \}\)/)
  assert.match(editorPage, /function toggleSidebar\(sidebarName\) \{[\s\S]*?actions\.setActiveSidebar\(nextSidebar\)/)
  assert.match(editorPage, /function openOutline\(\) \{[\s\S]*?toggleSidebar\('outline'\)/)
  assert.match(editorPage, /:aria-pressed="activeSidebar === 'versionHistory'"/)
  assert.match(editor, /emit\('access-change',[\s\S]*?nodeCount: data\.nodeCount,[\s\S]*?versionCount: data\.versionCount,[\s\S]*?updateTime: data\.updateTime/)
  assert.match(editorPage, /class="meta-save-status"[\s\S]*?\{\{ saveStatusText \}\}/)
  assert.match(editorPage, /class="meta-realtime-status"[\s\S]*?:aria-label="realtimeStatusText"/)
  assert.match(editorPage, /class="header-icon-btn save-action-btn"[\s\S]*?class="header-action-label">保存<\/span>/)
  assert.match(editorPage, /--mindmap-shell-top: 52px/)
  assert.match(editorPage, /--mindmap-activity-width: 44px/)
  assert.match(editorPage, /--mindmap-side-panel-width: 300px/)
  assert.match(editorPage, /--mindmap-workspace-bottom: 30px/)
  assert.match(editorPage, /--mindmap-canvas-gap: 8px/)
  assert.match(editorPage, /\.mindmap-edit-header \{\s*height: 52px/)
  assert.match(editor, /top: var\(--mindmap-canvas-gap, 8px\)/)
  assert.match(editor, /border-radius: 10px/)
  assert.match(toolbar, /@media \(max-width: 1600px\)/)
  assert.match(editorPage, /id="mindmap-mobile-command-sheet"[\s\S]*?:role="mobileCommandOpen \? 'dialog' : undefined"/)
  assert.match(editorPage, /class="header-icon-btn mobile-command-trigger"[\s\S]*?aria-controls="mindmap-mobile-command-sheet"[\s\S]*?:aria-expanded="mobileCommandOpen"/)
  assert.match(editorPage, /class="mobile-command-close"[\s\S]*?aria-label="关闭编辑命令"/)
  assert.match(editorPage, /function handleMobileCommandKeydown\(event\) \{[\s\S]*?event\.key === 'Escape'[\s\S]*?closeMobileCommands\(\)/)
  assert.match(editorPage, /event\.key !== 'Tab'[\s\S]*?querySelectorAll\?\.[\s\S]*?event\.shiftKey[\s\S]*?last\.focus\(\)/)
  assert.match(editorPage, /function closeMobileCommands\([\s\S]*?mobileCommandTriggerRef\.value\?\.focus\?\.\(\)/)
  assert.match(editorPage, /watch\(\[documentLoaded, isReadonly, isZenMode\][\s\S]*?closeMobileCommands\(\{ restoreFocus: false \}\)/)
  assert.match(editorPage, /@media \(max-width: 760px\)[\s\S]*?\.header-command-center \{[\s\S]*?&\.is-mobile-open \{[\s\S]*?display: flex/)
  assert.match(editorPage, /\.mobile-command-backdrop \{[\s\S]*?position: fixed[\s\S]*?inset: 0/)
  assert.doesNotMatch(editorPage, /mindmap-command-bar/)
  assert.match(toolbar, /embedded: \{\s*type: Boolean/)
  assert.match(toolbar, /&\.embedded \{[\s\S]*?position: static/)
  assert.match(toolbar, /&\.embedded \{[\s\S]*?\.toolbarBlock \{[\s\S]*?background: transparent/)
})

test('底部缩放、全屏和演示控件支持键盘并暴露操作名称', async () => {
  const [scale, fullscreen, demonstrate] = await Promise.all([
    readFile(scaleSourceUrl, 'utf8'),
    readFile(fullscreenSourceUrl, 'utf8'),
    readFile(demonstrateSourceUrl, 'utf8'),
  ])

  for (const source of [scale, fullscreen, demonstrate]) {
    assert.equal(/<div[^>]*class="[^"]*btn[^"]*"[^>]*@click/.test(source), false)
    assert.match(source, /<button[\s\S]*type="button"[\s\S]*aria-label=/)
  }
  assert.match(scale, /aria-label="画布缩放百分比"/)
  assert.match(demonstrate, /:disabled="curStepIndex <= 0"/)
  assert.match(demonstrate, /:disabled="curStepIndex >= totalStep - 1"/)
  assert.match(demonstrate, /aria-live="polite"/)
})
