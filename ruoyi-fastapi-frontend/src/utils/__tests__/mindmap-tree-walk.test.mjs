import assert from 'node:assert/strict'
import test from 'node:test'

import { walk } from '../../libs/simple-mind-map/src/utils/treeWalk.js'

function node(uid, children = []) {
  return { uid, children }
}

test('迭代 DFS 保持前序、后序及父级层级索引祖先契约', () => {
  const root = node('root', [
    node('a', [node('a-1')]),
    node('b'),
  ])
  const before = []
  const after = []

  walk(
    root,
    null,
    (current, parent, isRoot, level, index, ancestors) => {
      before.push({
        uid: current.uid,
        parent: parent?.uid || null,
        isRoot,
        level,
        index,
        ancestors: ancestors.map(item => item.uid),
      })
    },
    current => after.push(current.uid),
    true,
  )

  assert.deepEqual(before, [
    { uid: 'root', parent: null, isRoot: true, level: 0, index: 0, ancestors: [] },
    { uid: 'a', parent: 'root', isRoot: false, level: 1, index: 0, ancestors: ['root'] },
    { uid: 'a-1', parent: 'a', isRoot: false, level: 2, index: 0, ancestors: ['root', 'a'] },
    { uid: 'b', parent: 'root', isRoot: false, level: 1, index: 1, ancestors: ['root'] },
  ])
  assert.deepEqual(after, ['a-1', 'a', 'b', 'root'])
})

test('前置回调停止子树时仍执行当前节点后置回调', () => {
  const before = []
  const after = []
  const root = node('root', [node('skip', [node('hidden')]), node('visible')])

  walk(
    root,
    null,
    current => {
      before.push(current.uid)
      return current.uid === 'skip'
    },
    current => after.push(current.uid),
    true,
  )

  assert.deepEqual(before, ['root', 'skip', 'visible'])
  assert.deepEqual(after, ['skip', 'visible', 'root'])
})

test('活动路径循环会跳过而不同分支共享对象仍按原树语义访问', () => {
  const shared = node('shared')
  const root = node('root', [node('a', [shared]), node('b', [shared])])
  root.children.push(root)
  const visited = []

  walk(root, null, current => {
    visited.push(current.uid)
  }, null, true)

  assert.deepEqual(visited, ['root', 'a', 'shared', 'b', 'shared'])
})

test('二万层遍历不依赖调用栈且无需祖先的回调保持线性路径状态', () => {
  const root = node('0')
  let current = root
  for (let index = 1; index < 20000; index += 1) {
    const child = node(String(index))
    current.children = [child]
    current = child
  }

  let count = 0
  let deepestLevel = 0
  walk(root, null, (_node, _parent, _isRoot, level) => {
    count += 1
    deepestLevel = level
  }, null, true)

  assert.equal(count, 20000)
  assert.equal(deepestLevel, 19999)
})
