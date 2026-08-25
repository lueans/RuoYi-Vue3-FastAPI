import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)

async function readComponent(name) {
  return readFile(new URL(name, componentRoot), 'utf8')
}

test('常驻上下文编辑器在只读切换时关闭并禁用交互控件', async () => {
  const files = [
    'NodeIconToolbar.vue',
    'NodeImgPlacementToolbar.vue',
    'RichTextToolbar.vue',
    'AssociativeLineStyle.vue',
    'NodeOuterFrame.vue',
  ]
  const sources = await Promise.all(files.map(readComponent))

  for (const [index, source] of sources.entries()) {
    assert.match(source, /const isReadonly = computed\(\(\) => store\.isReadonly\)/, files[index])
    assert.match(source, /watch\(isReadonly,/, files[index])
    assert.match(source, /:disabled="isReadonly/, files[index])
  }

  assert.match(sources[0], /watch\(isReadonly,[\s\S]*if \(readonly\) close\(\)/)
  assert.match(sources[1], /watch\(isReadonly,[\s\S]*if \(readonly\) close\(\)/)
  assert.match(sources[2], /watch\(isReadonly,[\s\S]*if \(readonly\) closeToolbar\(\)/)
  assert.match(sources[3], /watch\(isReadonly,[\s\S]*onLineDeactivate\(\)/)
  assert.match(sources[4], /watch\(isReadonly,[\s\S]*onFrameDeactivate\(\)/)
})

test('上下文写操作在执行边界重新校验只读状态', async () => {
  const [icon, imagePlacement, richText, lineStyle, outerFrame] = await Promise.all([
    readComponent('NodeIconToolbar.vue'),
    readComponent('NodeImgPlacementToolbar.vue'),
    readComponent('RichTextToolbar.vue'),
    readComponent('AssociativeLineStyle.vue'),
    readComponent('NodeOuterFrame.vue'),
  ])

  assert.match(icon, /function show\(node, iconKey\)[\s\S]*?isReadonly\.value[\s\S]*?\) return/)
  assert.match(icon, /function setIcon\(name\)[\s\S]*?isReadonly\.value[\s\S]*?\) return/)
  assert.match(icon, /function deleteIcon\(\)[\s\S]*?isReadonly\.value[\s\S]*?\) return/)
  assert.match(imagePlacement, /function showAt\(node, imgEl\)[\s\S]*?isReadonly\.value[\s\S]*?\) return/)
  assert.match(imagePlacement, /function setPlacement\(val\)[\s\S]*?isReadonly\.value[\s\S]*?\) return/)
  assert.match(richText, /function getCurrentRichTextPlugin\(\)[\s\S]*isReadonly\.value[\s\S]*currentMindMap !== props\.mindMap[\s\S]*return currentMindMap\.richText/)
  assert.equal((richText.match(/getCurrentRichTextPlugin\(\)\?\./g) || []).length >= 6, true)
  assert.match(lineStyle, /function updateStyle\(prop\)[\s\S]*?isReadonly\.value[\s\S]*?\) return/)
  assert.match(outerFrame, /function updateFrame\(key, val\) \{\s*if \(isReadonly\.value \|\|/)
  assert.match(outerFrame, /function removeFrame\(\) \{\s*if \(isReadonly\.value \|\|/)
})

test('实例绑定浮层在首次挂载和切换脑图时成对订阅并清理旧目标', async () => {
  const [icon, imagePlacement, richText, lineStyle, outerFrame, editor] = await Promise.all([
    readComponent('NodeIconToolbar.vue'),
    readComponent('NodeImgPlacementToolbar.vue'),
    readComponent('RichTextToolbar.vue'),
    readComponent('AssociativeLineStyle.vue'),
    readComponent('NodeOuterFrame.vue'),
    readComponent('Edit.vue'),
  ])

  assert.match(icon, /let currentMindMap = null/)
  assert.match(icon, /watch\(\(\) => props\.mindMap,[\s\S]*if \(mm !== oldMm\) close\(\)[\s\S]*\{ immediate: true \}/)
  assert.match(icon, /currentMindMap !== props\.mindMap[\s\S]*currentNode\.mindMap !== currentMindMap/)

  assert.match(imagePlacement, /let currentMindMap = null/)
  assert.match(imagePlacement, /watch\(\(\) => props\.mindMap,[\s\S]*if \(mm !== oldMm\) close\(\)[\s\S]*\{ immediate: true \}/)
  assert.match(imagePlacement, /currentMindMap !== props\.mindMap[\s\S]*currentNode\.mindMap !== currentMindMap/)

  assert.match(editor, /forwardEvents\.forEach\(eventName => \{[\s\S]*bus\.emit\(eventName, \.\.\.args, mm\)/)
  assert.match(richText, /function onRichTextSelectionChange\(hasRange, rect, info, sourceMindMap = null\)/)
  assert.match(richText, /activeMindMap !== props\.mindMap/)
  assert.match(richText, /watch\(\(\) => props\.mindMap,[\s\S]*closeToolbar\(\)/)
  assert.match(richText, /onBeforeUnmount\(\(\) => \{\s*closeToolbar\(\)/)

  assert.match(lineStyle, /watch\(\(\) => props\.mindMap,[\s\S]*if \(mm !== oldMm\) onLineDeactivate\(\)[\s\S]*\{ immediate: true \}/)
  assert.match(lineStyle, /activeLineNode\.mindMap !== activeMindMap[\s\S]*activeLineToNode\.mindMap !== activeMindMap/)
  assert.match(lineStyle, /const existingStyle = \{ \.\.\.\(activeLineNode\.getData\('associativeLineStyle'\) \|\| \{\}\) \}/)
  assert.match(lineStyle, /onBeforeUnmount\(\(\) => \{\s*onLineDeactivate\(\)/)

  assert.match(outerFrame, /let currentMindMap = null/)
  assert.match(outerFrame, /watch\(\(\) => props\.mindMap,[\s\S]*if \(mm !== oldMm\) onFrameDeactivate\(\)[\s\S]*\{ immediate: true \}/)
  assert.match(outerFrame, /currentMindMap !== props\.mindMap/)
  assert.match(outerFrame, /removeActiveOuterFrame\?\.\(\)[\s\S]*onFrameDeactivate\(\)/)
})
