import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createNewOutlineNode,
  createOutlineTreeNode,
} from '../mindmap-outline-edit.js'

test('大纲快照保留富文本和节点扩展数据供节点级编辑使用', () => {
  let sequence = 0
  const source = {
    data: {
      uid: 'root',
      text: '<strong>项目</strong> <em>计划</em>',
      richText: true,
      icon: ['priority_1'],
    },
    children: [{
      data: { uid: 'child', text: '<u>里程碑</u>', richText: true },
      children: [],
    }],
  }

  const outline = createOutlineTreeNode(source, () => `generated-${++sequence}`)
  assert.equal(outline.label, '项目 计划')
  assert.deepEqual(outline.originalData, source.data)
  assert.deepEqual(outline.children[0].originalData, source.children[0].data)
  assert.equal(outline.isNew, false)
  assert.equal(sequence, 0)
})

test('兼容旧节点缺失 UID 时只补一个稳定身份', () => {
  let calls = 0
  const outline = createOutlineTreeNode(
    { data: { text: '旧节点' }, children: [] },
    () => `legacy-${++calls}`,
  )

  assert.equal(calls, 1)
  assert.equal(outline.uid, 'legacy-1')
  assert.equal(outline.originalData.uid, 'legacy-1')
})

test('新增大纲节点只生成一次 UID 并复用于持久化数据', () => {
  let calls = 0
  const node = createNewOutlineNode(() => {
    calls += 1
    return 'new-node-uid'
  })

  assert.equal(calls, 1)
  assert.equal(node.uid, 'new-node-uid')
  assert.equal(node.originalData.uid, 'new-node-uid')
  assert.equal(node.isNew, true)
})

test('大纲编辑使用节点级命令并在快捷新增前同步当前标题', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/OutlineEdit.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /execCommand\('SET_NODE_TEXT'/)
  assert.match(source, /execCommand\('INSERT_NODE'/)
  assert.match(source, /execCommand\('INSERT_CHILD_NODE'/)
  assert.match(source, /execCommand\('MOVE_NODE_TO'/)
  assert.match(source, /execCommand\('INSERT_BEFORE'/)
  assert.match(source, /execCommand\('INSERT_AFTER'/)
  assert.match(source, /updateNodeLabel\(e\.currentTarget, data\)[\s\S]*createNewOutlineNode/)
  assert.match(source, /:allow-drag="allowDrag"/)
  assert.match(source, /return !isReadonly\.value && node\.level > 1/)
  assert.match(source, /function close\(\) \{[\s\S]*blurActiveOutlineEditor\(\)/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*blurActiveOutlineEditor\(\)/)
  assert.doesNotMatch(source, /bus\.emit\('setData'/)
  assert.doesNotMatch(source, /document\.(?:addEventListener|removeEventListener)\('keydown'/)
  assert.doesNotMatch(source, /function onKeydown/)
  assert.doesNotMatch(source, /uid: createUid\(\), originalData: \{ text: '新节点', uid: createUid\(\)/)
})

test('大纲编辑在只读切换前后都具备纵深写入防护', async () => {
  const [editor, sidebar] = await Promise.all([
    readFile(new URL('../../components/MindMap/OutlineEdit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/OutlineSidebar.vue', import.meta.url), 'utf8'),
  ])

  assert.match(sidebar, /:disabled="isReadonly"/)
  assert.match(sidebar, /function openOutlineEdit\(\) \{\s*if \(isReadonly\.value\) return/)
  assert.match(editor, /:contenteditable="!isReadonly"/)
  assert.match(editor, /:draggable="!isReadonly"/)
  assert.match(editor, /function openOutlineEdit\(\) \{\s*if \(isOutlineEdit\.value \|\| isReadonly\.value\) return/)
  assert.match(editor, /function updateNodeLabel\([^)]*\) \{\s*if \(isReadonly\.value\) return/)
  assert.match(editor, /function onNodeDrop\([^)]*\) \{\s*if \(isReadonly\.value\) return/)
  assert.match(editor, /watch\(isReadonly, \(readonly\) => \{[\s\S]*?if \(readonly && isOutlineEdit\.value\) close\(\)/)
  assert.match(editor, /bus\.on\('closeOutlineEdit', close\)/)
  assert.match(editor, /bus\.off\('closeOutlineEdit', close\)/)
})
