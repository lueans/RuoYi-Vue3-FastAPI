import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  isCurrentMindmapEventSource,
  resolveMindmapEventNodes,
} from '../mindmap-event.js'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)

async function readComponent(file) {
  return readFile(new URL(file, componentRoot), 'utf8')
}

test('脑图事件只接受当前实例并兼容未携带来源的内部调用', () => {
  const currentMindMap = {}
  const staleMindMap = {}

  assert.equal(isCurrentMindmapEventSource(currentMindMap, currentMindMap), true)
  assert.equal(isCurrentMindmapEventSource(null, currentMindMap), true)
  assert.equal(isCurrentMindmapEventSource(staleMindMap, currentMindMap), false)
  assert.equal(isCurrentMindmapEventSource(currentMindMap, null), false)
})

test('活动节点解析拒绝旧实例、外来节点和重复对象', () => {
  const currentMindMap = {}
  const staleMindMap = {}
  const currentNode = { mindMap: currentMindMap }
  const legacyNodeWithoutOwner = {}
  const foreignNode = { mindMap: staleMindMap }

  assert.equal(resolveMindmapEventNodes([currentNode], staleMindMap, currentMindMap), null)
  assert.deepEqual(resolveMindmapEventNodes(null, currentMindMap, currentMindMap), [])
  assert.deepEqual(
    resolveMindmapEventNodes(
      [null, currentNode, currentNode, foreignNode, legacyNodeWithoutOwner],
      currentMindMap,
      currentMindMap,
    ),
    [currentNode, legacyNodeWithoutOwner],
  )
})

test('活动节点组合式能力统一订阅、切图清理和当前实例同步', async () => {
  const [composable, editor] = await Promise.all([
    readComponent('useMindMapActiveNodes.js'),
    readComponent('Edit.vue'),
  ])

  assert.match(composable, /resolveMindmapEventNodes\(nodeList, sourceMindMap, currentMindMap\)/)
  assert.match(composable, /watch\(resolveMindMap,[\s\S]*clearActiveNodes\(\)[\s\S]*onMindMapChange\?\./)
  assert.match(composable, /bus\.on\('node_active', onNodeActive\)/)
  assert.match(composable, /bus\.off\('node_active', onNodeActive\)/)
  assert.match(composable, /currentMindMap\.renderer\?\.activeNodeList/)

  for (const eventName of [
    'back_forward',
    'node_active',
    'node_contextmenu',
    'node_note_dblclick',
    'node_attachmentClick',
    'node_attachmentContextmenu',
    'painter_start',
    'painter_end',
  ]) {
    assert.match(editor, new RegExp(`'${eventName}'`))
  }
  assert.match(editor, /forwardEvents\.forEach\(eventName => \{[\s\S]*bus\.emit\(eventName, \.\.\.args, mm\)/)
  assert.doesNotMatch(editor, /bus\.emit\(eventName, \.\.\.args\)\s*$/m)
})

test('保存、派生视图和演示状态只响应当前脑图的运行时事件', async () => {
  const [editor, outline, navigator, count, demonstrate] = await Promise.all([
    readComponent('Edit.vue'),
    readComponent('OutlineSidebar.vue'),
    readComponent('Navigator.vue'),
    readComponent('Count.vue'),
    readComponent('Demonstrate.vue'),
  ])

  for (const eventName of [
    'data_change',
    'view_data_change',
    'node_tree_render_end',
    'hide_text_edit',
    'demonstrate_jump',
    'enter_demonstrate',
    'exit_demonstrate',
  ]) {
    assert.match(editor, new RegExp(`'${eventName}'`))
  }
  assert.match(editor, /function onBusDataChange\(data, sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource\(sourceMindMap, mindMap\.value\)/)
  assert.match(editor, /function onBusViewDataChange\(data, sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource\(sourceMindMap, mindMap\.value\)/)
  assert.match(editor, /function onHideTextEdit\(\.\.\.args\)[\s\S]*isCurrentMindmapEventSource\(sourceMindMap, mindMap\.value\)/)
  assert.equal((outline.match(/isCurrentMindmapEventSource\(sourceMindMap, props\.mindMap\)/g) || []).length >= 2, true)
  assert.equal((navigator.match(/isCurrentMindmapEventSource\(sourceMindMap, props\.mindMap\)/g) || []).length >= 3, true)
  assert.match(count, /function onDataChange\(data, sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource\(sourceMindMap, props\.mindMap\)/)
  assert.equal((demonstrate.match(/isCurrentMindmapEventSource\(sourceMindMap, props\.mindMap\)/g) || []).length >= 3, true)
  assert.match(demonstrate, /const el = mindMap\?\.el/)
})

test('选区消费者和直接节点动作统一执行来源实例校验', async () => {
  const selectionConsumers = [
    'NodeImage.vue',
    'NodeHyperlink.vue',
    'NodeAttachment.vue',
    'NodeNote.vue',
    'NodeTag.vue',
    'NodeIconSidebar.vue',
    'Style.vue',
    'Toolbar.vue',
  ]
  const sources = await Promise.all(selectionConsumers.map(readComponent))

  for (const [index, source] of sources.entries()) {
    assert.match(source, /useMindMapActiveNodes\(/, selectionConsumers[index])
  }

  const [attachment, toolbar, contextmenu, noteSidebar, noteContent, formula, editor] = await Promise.all([
    readComponent('NodeAttachment.vue'),
    readComponent('Toolbar.vue'),
    readComponent('Contextmenu.vue'),
    readComponent('NodeNoteSidebar.vue'),
    readComponent('NodeNoteContentShow.vue'),
    readComponent('FormulaSidebar.vue'),
    readComponent('Edit.vue'),
  ])
  assert.equal((attachment.match(/isCurrentMindmapEventSource\(sourceMindMap, store\.mindMap\)/g) || []).length >= 2, true)
  assert.equal((toolbar.match(/isCurrentMindmapEventSource\(sourceMindMap, store\.mindMap\)/g) || []).length >= 4, true)
  assert.match(contextmenu, /function show\(e, n, sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource/)
  assert.match(contextmenu, /function hideFromMindMapEvent\(\.\.\.args\)/)
  assert.match(noteSidebar, /function onNodeActive\(_node, _nodeList, sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource/)
  assert.match(noteContent, /function scheduleHideNote\(sourceMindMap = null\)[\s\S]*isCurrentMindmapEventSource/)
  assert.match(noteContent, /function hideNoteFromMindMapEvent\(\.\.\.args\)[\s\S]*isCurrentMindmapEventSource/)
  assert.match(editor, /bus\.emit\('showNoteContent', content, left, top, node, noteContentMindMap\)/)
  assert.match(editor, /bus\.emit\('scheduleHideNoteContent', noteContentMindMap\)/)
  assert.match(formula, /resolveMindmapEventNodes\(nodeList, sourceMindMap, props\.mindMap\)/)
})
