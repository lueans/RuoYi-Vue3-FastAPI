import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const toolbarSourceUrl = new URL('../../components/MindMap/Toolbar.vue', import.meta.url)
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
