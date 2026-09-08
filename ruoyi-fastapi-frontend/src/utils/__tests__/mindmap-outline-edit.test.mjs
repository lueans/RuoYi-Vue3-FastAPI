import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createNewOutlineNode,
  createOutlineRefreshGate,
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

test('双端远端渲染在空闲时刷新大纲，本地编辑时保留 DOM 输入到释放后', () => {
  let open = true
  let activeLeaseUid = ''
  let localDomInput = ''
  let refreshCount = 0
  const scheduled = []
  const gate = createOutlineRefreshGate({
    isOpen: () => open,
    hasLocalEdit: () => Boolean(activeLeaseUid),
    schedule: callback => scheduled.push(callback),
    refresh: () => { refreshCount += 1 },
  })

  // 浏览器 B 的增删/改名渲染到浏览器 A 时，A 空闲则在下一批次刷新。
  assert.equal(gate.request(), true)
  assert.equal(refreshCount, 0)
  scheduled.shift()()
  assert.equal(refreshCount, 1)

  // A 正在输入时只标记待刷新，不替换 contenteditable DOM。
  activeLeaseUid = 'node-a'
  localDomInput = '未提交标题'
  gate.request()
  assert.equal(scheduled.length, 0)
  assert.equal(localDomInput, '未提交标题')
  assert.equal(refreshCount, 1)

  activeLeaseUid = ''
  assert.equal(gate.flush(), true)
  scheduled.shift()()
  assert.equal(refreshCount, 2)

  open = false
  assert.equal(gate.request(), false)
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
  assert.match(source, /@focus="onNodeFocus\(\$event, data\)"/)
  assert.match(source, /runtimeNode\.isTextEditOccupied\?\.\(\)/)
  assert.match(source, /async function onNodeFocus/)
  assert.match(source, /pendingOutlineLeaseUid = data\.uid[\s\S]*target\?\.blur\?\.\(\)[\s\S]*await beforeTextEdit/)
  assert.match(source, /activeOutlineLeaseUid = data\.uid[\s\S]*emit\?\.\('node_text_edit_start', currentRuntimeNode\)/)
  assert.match(source, /function releaseOutlineLease[\s\S]*'node_text_edit_end'/)
  assert.match(source, /function onNodeBlur[\s\S]*try \{[\s\S]*updateNodeLabel[\s\S]*finally \{[\s\S]*releaseOutlineLease/)
  assert.match(source, /function updateNodeLabel[\s\S]*execCommand\('SET_NODE_TEXT'[\s\S]*finally \{[\s\S]*flushPendingHistory\?\.\(\)/)
  assert.match(source, /defineExpose\(\{ getActiveTextEditor \}\)/)
  assert.match(source, /function getActiveTextEditor[\s\S]*nodeUid[\s\S]*getEditText:[\s\S]*target\.textContent[\s\S]*hideEditTextBox[\s\S]*onNodeBlur/)
  assert.match(source, /mindMap\.on\?\.\('node_tree_render_end', onMindMapRenderEnd\)/)
  assert.match(source, /unbindRenderEvents\(\)/)
  assert.match(source, /if \(outlineRefreshGate\.pending\)[\s\S]*releaseOutlineLease[\s\S]*outlineRefreshGate\.flush\(\)/)
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

test('大纲获锁后若复焦条件失效会清理本地状态并释放服务端租约', async () => {
  const editor = await readFile(
    new URL('../../components/MindMap/OutlineEdit.vue', import.meta.url),
    'utf8',
  )
  const focusBlock = editor.match(
    /async function onNodeFocus[\s\S]*?\n\}\n\nfunction releaseDetachedOutlineLease/,
  )?.[0] || ''
  const cleanupBranches = focusBlock.match(
    /else if \(activeOutlineLeaseUid === data\.uid\)/g,
  ) || []

  assert.equal(cleanupBranches.length, 1)
  assert.match(
    focusBlock,
    /else if \(activeOutlineLeaseUid === data\.uid\) \{\s*activeOutlineLeaseUid = ''[\s\S]*?releaseOutlineLease\(data\.uid, currentRuntimeNode\)/,
  )
})
