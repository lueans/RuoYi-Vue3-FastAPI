import assert from 'node:assert/strict'
import test from 'node:test'

import { rebaseMindmapHistory } from '../mindmap-history-rebase.js'

const createTree = ({ localText = '本地旧值', remoteText = '远端旧值' } = {}) => ({
  data: { uid: 'root', text: '根节点' },
  children: [
    { data: { uid: 'local', text: localText }, children: [] },
    { data: { uid: 'remote', text: remoteText }, children: [] },
  ],
  smmVersion: '1.0.0',
})

test('远端修改不同节点时会重放到全部撤销快照', () => {
  const beforeLocalEdit = createTree()
  const currentTree = createTree({ localText: '本地新值' })
  const remoteTree = createTree({ localText: '本地新值', remoteText: '远端新值' })

  const result = rebaseMindmapHistory({
    history: [JSON.stringify(beforeLocalEdit), JSON.stringify(currentTree)],
    activeHistoryIndex: 1,
    currentTree,
    remoteTree,
  })

  assert.ok(result)
  assert.equal(result.activeHistoryIndex, 1)
  const undoSnapshot = JSON.parse(result.history[0])
  const currentSnapshot = JSON.parse(result.history[1])
  assert.equal(undoSnapshot.children[0].data.text, '本地旧值')
  assert.equal(undoSnapshot.children[1].data.text, '远端新值')
  assert.equal(currentSnapshot.children[0].data.text, '本地新值')
  assert.equal(currentSnapshot.children[1].data.text, '远端新值')
})

test('本地与远端修改同一节点时拒绝重放旧历史', () => {
  const beforeLocalEdit = createTree()
  const currentTree = createTree({ localText: '本地新值' })
  const remoteTree = createTree({ localText: '远端竞争值' })

  assert.equal(rebaseMindmapHistory({
    history: [JSON.stringify(beforeLocalEdit), JSON.stringify(currentTree)],
    activeHistoryIndex: 1,
    currentTree,
    remoteTree,
  }), null)
})

test('远端新增节点会出现在每一份本地历史中', () => {
  const beforeLocalEdit = createTree()
  const currentTree = createTree({ localText: '本地新值' })
  const remoteTree = structuredClone(currentTree)
  remoteTree.children.push({ data: { uid: 'created', text: '远端新增' }, children: [] })

  const result = rebaseMindmapHistory({
    history: [JSON.stringify(beforeLocalEdit), JSON.stringify(currentTree)],
    activeHistoryIndex: 1,
    currentTree,
    remoteTree,
  })

  assert.ok(result)
  for (const entry of result.history) {
    assert.equal(JSON.parse(entry).children.at(-1).data.uid, 'created')
  }
})

test('撤销后收到远端修改会丢弃旧的重做分支', () => {
  const beforeLocalEdit = createTree()
  const currentTree = createTree({ localText: '本地新值' })
  const abandonedRedo = createTree({ localText: '已撤销的后续值' })
  const remoteTree = createTree({ localText: '本地新值', remoteText: '远端新值' })

  const result = rebaseMindmapHistory({
    history: [
      JSON.stringify(beforeLocalEdit),
      JSON.stringify(currentTree),
      JSON.stringify(abandonedRedo),
    ],
    activeHistoryIndex: 1,
    currentTree,
    remoteTree,
  })

  assert.ok(result)
  assert.equal(result.history.length, 2)
  assert.equal(JSON.parse(result.history.at(-1)).children[0].data.text, '本地新值')
})

test('损坏的历史快照会安全回退为清空历史', () => {
  assert.equal(rebaseMindmapHistory({
    history: ['{broken'],
    activeHistoryIndex: 0,
    currentTree: createTree(),
    remoteTree: createTree({ remoteText: '远端新值' }),
  }), null)
})
