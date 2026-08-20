import assert from 'node:assert/strict'
import test from 'node:test'

import { captureMindmapEditTargets } from '../mindmap-edit-targets.js'

const createNode = id => ({ id, getData() {} })

test('节点编辑目标按对象身份去重并冻结为选区快照', () => {
  const first = createNode(1)
  const second = createNode(2)
  const activeNodes = [first, null, first, {}, second]

  const snapshot = captureMindmapEditTargets(activeNodes)
  activeNodes.splice(0)

  assert.deepEqual(snapshot, [first, second])
  assert.equal(Object.isFrozen(snapshot), true)
  assert.throws(() => snapshot.push(createNode(3)), TypeError)
})

test('右键指定节点优先于当前多选节点且非法输入返回空快照', () => {
  const first = createNode(1)
  const appointed = createNode(9)

  assert.deepEqual(captureMindmapEditTargets([first], appointed), [appointed])
  assert.deepEqual(captureMindmapEditTargets(null), [])
  assert.deepEqual(captureMindmapEditTargets([{}], {}), [])
})
