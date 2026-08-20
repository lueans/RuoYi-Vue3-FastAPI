import assert from 'node:assert/strict'
import test from 'node:test'

import { applyMindmapDocumentPreservingRuntimeState } from '../mindmap-document-apply.js'

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
      applyMindmapDocumentPreservingRuntimeState(mindMap, next),
      'full',
    )
    assert.deepEqual(mindMap.calls, ['setFullData'])
  }
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
