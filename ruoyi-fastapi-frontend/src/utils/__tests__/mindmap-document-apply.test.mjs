import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyMindmapActiveCrossNodeEditorSnapshots,
  applyMindmapActiveEditorTextSnapshots,
  applyAuthoritativeMindmapDocument,
  applyMindmapDocumentPreservingRuntimeState,
  findMindmapTreeNodeByUid,
  mindmapDocumentRequiresFullRuntimeReplacement,
  mindmapTreeContainsAssociativeLine,
  mindmapTreeContainsExactOuterFrame,
  mindmapTreeContainsNodeUid,
  mindmapTreeNodesHaveSameEditableData,
  mindmapTreesHaveSameCrossNodeState,
} from '../mindmap-document-apply.js'

test('活动 DOM 文本只写入恢复快照且保留未命中节点', () => {
  const document = {
    root: {
      data: { uid: 'root', text: '根节点' },
      children: [
        { data: { uid: 'plain', text: '模型旧值', color: '#fff' }, children: [] },
        { data: { uid: 'rich', text: '<p>旧值</p>', richText: true }, children: [] },
      ],
    },
    layout: 'logicalStructure',
  }

  const result = applyMindmapActiveEditorTextSnapshots(document, [
    { nodeUid: 'plain', text: 'DOM 最后输入' },
    { nodeUid: 'rich', text: '<p>DOM <strong>最后输入</strong></p>', richText: true },
    { nodeUid: 'missing', text: '不得创建幽灵节点', richText: false },
    { nodeUid: 'plain', text: 123 },
  ])

  assert.strictEqual(result, document)
  assert.equal(document.root.children[0].data.text, 'DOM 最后输入')
  assert.equal(document.root.children[0].data.color, '#fff')
  assert.equal(document.root.children[0].data.richText, undefined)
  assert.equal(
    document.root.children[1].data.text,
    '<p>DOM <strong>最后输入</strong></p>',
  )
  assert.equal(document.root.children[1].data.richText, true)
  assert.equal(document.root.children.length, 2)
})

test('关联线和外框 DOM 文本只覆盖恢复快照中的精确跨节点实体', () => {
  const frame = (groupId, text) => ({ groupId, text, color: '#09f' })
  const document = {
    root: {
      data: { uid: 'root' },
      children: [
        {
          data: {
            uid: 'source',
            associativeLineTargets: ['target'],
            associativeLineText: { target: '旧连线文字' },
          },
          children: [],
        },
        { data: { uid: 'target' }, children: [] },
        { data: { uid: 'frame-a', outerFrame: frame('frame-1', '旧外框') }, children: [] },
        { data: { uid: 'frame-b', outerFrame: frame('frame-1', '旧外框') }, children: [] },
      ],
    },
  }

  applyMindmapActiveCrossNodeEditorSnapshots(document, [
    {
      kind: 'associative-line',
      sourceUid: 'source',
      targetUid: 'target',
      text: 'DOM 连线文字',
    },
    {
      kind: 'outer-frame',
      groupUid: 'frame-1',
      memberUids: ['frame-a', 'frame-b'],
      text: 'DOM 外框文字',
    },
    {
      kind: 'outer-frame',
      groupUid: 'frame-1',
      memberUids: ['frame-a'],
      text: '不得部分覆盖',
    },
  ])

  assert.equal(document.root.children[0].data.associativeLineText.target, 'DOM 连线文字')
  assert.equal(document.root.children[2].data.outerFrame.text, 'DOM 外框文字')
  assert.equal(document.root.children[3].data.outerFrame.text, 'DOM 外框文字')
  assert.equal(document.root.children[2].data.outerFrame.color, '#09f')
})

test('node identity lookup supports deep trees and ignores cycles', () => {
  const root = { data: { uid: 'root' }, children: [] }
  let current = root
  for (let index = 0; index < 5_000; index += 1) {
    const child = { data: { uid: `node-${index}` }, children: [] }
    current.children.push(child)
    current = child
  }
  current.children.push(root)

  assert.equal(mindmapTreeContainsNodeUid(root, 'node-4999'), true)
  assert.equal(mindmapTreeContainsNodeUid(root, 'missing'), false)
  assert.equal(mindmapTreeContainsNodeUid(root, ''), false)
  assert.strictEqual(findMindmapTreeNodeByUid(root, 'node-4999'), current)
  assert.equal(findMindmapTreeNodeByUid(root, 'missing'), null)
})

test('节点编辑数据比较忽略无关结构、选区和跨节点记录', () => {
  const current = {
    data: { uid: 'root' },
    children: [
      {
        data: {
          uid: 'editing',
          text: '正在编辑',
          isActive: true,
          associativeLineTargets: ['other'],
          tag: [{ tagId: 7, categoryId: 2, name: '旧展示名', color: '#fff' }],
        },
        children: [],
      },
      { data: { uid: 'other', text: '旧值' }, children: [] },
    ],
  }
  const remote = structuredClone(current)
  remote.children[0].data.isActive = false
  remote.children[0].data.associativeLineTargets = []
  remote.children[0].data.tag[0].name = '云端展示名'
  remote.children[1].data.text = '协作者修改了其他节点'
  remote.children[0].children.push({ data: { uid: 'new-child' }, children: [] })

  assert.equal(
    mindmapTreeNodesHaveSameEditableData(current, remote, 'editing'),
    true,
  )

  remote.children[0].data.text = '协作者也修改了当前节点'
  assert.equal(
    mindmapTreeNodesHaveSameEditableData(current, remote, 'editing'),
    false,
  )
  assert.equal(
    mindmapTreeNodesHaveSameEditableData(current, remote, 'missing'),
    false,
  )
})

test('关联线编辑目标要求远端保留关系本身及两个端点', () => {
  const root = {
    data: { uid: 'root' },
    children: [
      {
        data: {
          uid: 'source',
          associativeLineTargets: ['target'],
          associativeLineText: { target: '本地输入' },
        },
        children: [],
      },
      { data: { uid: 'target' }, children: [] },
    ],
  }

  assert.equal(
    mindmapTreeContainsAssociativeLine(root, 'source', 'target'),
    true,
  )
  root.children[0].data.associativeLineTargets = []
  assert.equal(
    mindmapTreeContainsAssociativeLine(root, 'source', 'target'),
    false,
  )
  root.children[0].data.associativeLineTargets = ['target']
  root.children.pop()
  assert.equal(
    mindmapTreeContainsAssociativeLine(root, 'source', 'target'),
    false,
  )
})

test('外框编辑目标要求远端保留同一 groupId 和完整成员集合', () => {
  const frame = groupId => ({ groupId, text: '外框文字' })
  const root = {
    data: { uid: 'root' },
    children: [
      { data: { uid: 'a', outerFrame: frame('group-1') }, children: [] },
      { data: { uid: 'b', outerFrame: frame('group-1') }, children: [] },
      { data: { uid: 'c' }, children: [] },
    ],
  }

  assert.equal(
    mindmapTreeContainsExactOuterFrame(root, 'group-1', ['a', 'b']),
    true,
  )
  assert.equal(
    mindmapTreeContainsExactOuterFrame(root, 'group-1', ['a']),
    false,
    '远端多出的成员不能被本地旧成员列表覆盖',
  )
  root.children[1].data.outerFrame = null
  assert.equal(
    mindmapTreeContainsExactOuterFrame(root, 'group-1', ['a', 'b']),
    false,
  )
  assert.equal(
    mindmapTreeContainsExactOuterFrame(root, '', ['a']),
    false,
    '缺少稳定 groupId 时失败关闭，避免匹配到新建外框',
  )
})

test('浮层提交前会检测全部跨节点记录，避免回写旧画布覆盖无关远端变更', () => {
  const current = {
    data: { uid: 'root' },
    children: [
      {
        data: {
          uid: 'a',
          associativeLineTargets: ['b'],
          associativeLineText: { b: '原文字' },
        },
        children: [],
      },
      { data: { uid: 'b', text: '本地节点文字' }, children: [] },
    ],
  }
  const onlyNodeChanged = structuredClone(current)
  onlyNodeChanged.children[1].data.text = '远端节点文字'
  assert.equal(
    mindmapTreesHaveSameCrossNodeState(current, onlyNodeChanged),
    true,
  )

  const relationChanged = structuredClone(onlyNodeChanged)
  relationChanged.children[0].data.associativeLineText.b = '远端关系文字'
  assert.equal(
    mindmapTreesHaveSameCrossNodeState(current, relationChanged),
    false,
  )
})

function createMindMap(current) {
  const calls = []
  let document = structuredClone(current)
  return {
    calls,
    getData: () => structuredClone(document),
    updateData(root) {
      document.root = structuredClone(root)
      calls.push('updateData')
    },
    setFullData(value) {
      document = structuredClone(value)
      calls.push('setFullData')
    },
    view: {
      setTransformData(view) {
        document.view = structuredClone(view)
        calls.push('setTransformData')
      },
    },
  }
}

test('仅节点和视图更新保留运行时节点实例', () => {
  const current = {
    root: { data: { uid: 'root' }, children: [] },
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
    view: { transform: { scaleX: 1, scaleY: 1 } },
  }
  const mindMap = createMindMap(current)
  const next = structuredClone(current)
  next.root.data.text = '协作更新'
  next.view.transform.translateX = -200

  assert.equal(
    applyMindmapDocumentPreservingRuntimeState(mindMap, next),
    'incremental',
  )
  assert.deepEqual(mindMap.calls, ['updateData', 'setTransformData'])
})

test('布局或主题变化仍使用完整文档应用流程', () => {
  const current = {
    root: { data: { uid: 'root' }, children: [] },
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
  }
  for (const patch of [
    { layout: 'mindMap' },
    { theme: { template: 'dark', config: {} } },
  ]) {
    const mindMap = createMindMap(current)
    const next = { ...structuredClone(current), ...patch }
    assert.equal(
      mindmapDocumentRequiresFullRuntimeReplacement(mindMap, next),
      true,
    )
    assert.equal(
      applyMindmapDocumentPreservingRuntimeState(mindMap, next),
      'full',
    )
    assert.deepEqual(mindMap.calls, ['setFullData'])
  }

  const incrementalMindMap = createMindMap(current)
  assert.equal(
    mindmapDocumentRequiresFullRuntimeReplacement(
      incrementalMindMap,
      { root: structuredClone(current.root) },
    ),
    false,
  )
})

test('协作回放从正在编辑的节点恢复本地选中态且不重复应用相同视图', () => {
  const current = {
    root: {
      data: { uid: 'root' },
      children: [{ data: { uid: 'editing' }, children: [] }],
    },
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
    view: { state: { scale: 1, x: -20, y: 0 } },
  }
  const mindMap = createMindMap(current)
  mindMap.renderer = {
    activeNodeList: [],
    textEdit: {
      getCurrentEditNode: () => ({ uid: 'editing' }),
    },
  }
  const next = structuredClone(current)
  next.root.children[0].data.text = '远端内容'

  assert.equal(
    applyMindmapDocumentPreservingRuntimeState(mindMap, next),
    'incremental',
  )
  assert.deepEqual(mindMap.calls, ['updateData'])
  assert.equal(next.root.data.isActive, false)
  assert.equal(next.root.children[0].data.isActive, true)
})

test('权威树应用会取消延迟历史采集并在恢复命令前更新撤销基线', async () => {
  const current = {
    root: {
      data: { uid: 'root', text: '根节点' },
      children: [{ data: { uid: 'remote', text: '旧值' }, children: [] }],
    },
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
  }
  const mindMap = createMindMap(current)
  const originalUpdateData = mindMap.updateData.bind(mindMap)
  let timer = null
  let delayedLocalChangeCount = 0
  const addHistory = () => {
    if (timer !== null) return
    timer = setTimeout(() => {
      timer = null
      if (!mindMap.command.isPause) delayedLocalChangeCount += 1
    }, 10)
  }
  addHistory.cancel = () => {
    clearTimeout(timer)
    timer = null
  }
  mindMap.command = {
    history: [JSON.stringify(current.root)],
    activeHistoryIndex: 0,
    isPause: false,
    mindMap: { opt: {} },
    addHistory,
    getCopyData: () => mindMap.getData().root,
    pause() { this.isPause = true },
    recovery() { this.isPause = false },
    resetHistoryBaseline() {
      this.history = [JSON.stringify(this.getCopyData())]
      this.activeHistoryIndex = 0
    },
  }
  mindMap.updateData = (root) => {
    originalUpdateData(root)
    addHistory()
  }
  const next = structuredClone(current)
  next.root.children[0].data.text = '云端值'

  assert.equal(applyAuthoritativeMindmapDocument(mindMap, next), 'incremental')
  await new Promise(resolve => setTimeout(resolve, 30))

  assert.equal(delayedLocalChangeCount, 0)
  assert.equal(mindMap.command.isPause, false)
  assert.equal(
    JSON.parse(mindMap.command.history.at(-1)).children[0].data.text,
    '云端值',
  )
})

test('权威树与本地撤销历史竞争时建立当前静默基线', () => {
  const before = {
    data: { uid: 'root', text: '旧值' },
    children: [],
  }
  const current = {
    root: {
      data: { uid: 'root', text: '本地值' },
      children: [],
    },
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
  }
  const mindMap = createMindMap(current)
  let baselineResetCount = 0
  const addHistory = () => {}
  addHistory.cancel = () => {}
  mindMap.command = {
    history: [JSON.stringify(before), JSON.stringify(current.root)],
    activeHistoryIndex: 1,
    isPause: false,
    mindMap: { opt: {} },
    addHistory,
    getCopyData: () => mindMap.getData().root,
    pause() { this.isPause = true },
    recovery() { this.isPause = false },
    resetHistoryBaseline() {
      baselineResetCount += 1
      this.history = [JSON.stringify(this.getCopyData())]
      this.activeHistoryIndex = 0
    },
  }
  const next = structuredClone(current)
  next.root.data.text = '云端竞争值'

  applyAuthoritativeMindmapDocument(mindMap, next)

  assert.equal(baselineResetCount, 1)
  assert.equal(mindMap.command.history.length, 1)
  assert.equal(JSON.parse(mindMap.command.history[0]).data.text, '云端竞争值')
})
