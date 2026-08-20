import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MAX_XMIND_MINDMAP_DEPTH,
  MAX_XMIND_MINDMAP_NODE_COUNT,
  findFirstXmindElementByName,
  mapXmindTreeIterative
} from '../../libs/simple-mind-map/src/parse/xmindTree.js'

const mapTree = (root, options = {}) => mapXmindTreeIterative({
  root,
  visit(source, target, context) {
    target.value = source.value
    target.depth = context.depth
    target.children = []
    return { children: source.children }
  },
  getChildren: (source, context) => context.meta.children,
  createChild(parentTarget) {
    const child = {}
    parentTarget.children.push(child)
    return child
  },
  ...options
})

test('XMind 迭代映射保持稳定子序、层级和独立目标树', () => {
  const source = {
    value: 'root',
    children: [
      { value: 'a', children: [{ value: 'a-1' }] },
      { value: 'b' }
    ]
  }

  const target = mapTree(source)
  assert.deepEqual(target, {
    value: 'root',
    depth: 1,
    children: [
      {
        value: 'a',
        depth: 2,
        children: [{ value: 'a-1', depth: 3, children: [] }]
      },
      { value: 'b', depth: 2, children: [] }
    ]
  })
  assert.notEqual(target.children, source.children)
})

test('XMind 迭代映射接受 20,000 节点宽树并在发现阶段拒绝超限', () => {
  const root = {
    value: 'root',
    children: Array.from(
      { length: MAX_XMIND_MINDMAP_NODE_COUNT - 1 },
      (_, index) => ({ value: String(index) })
    )
  }
  const mapped = mapTree(root)
  assert.equal(mapped.children.length, MAX_XMIND_MINDMAP_NODE_COUNT - 1)

  root.children.push({ value: 'overflow' })
  assert.throws(() => mapTree(root), /节点数量不能超过 20000/)
})

test('XMind 层级边界与服务端 256 层持久化契约一致', () => {
  const createChain = length => {
    const root = { value: '1' }
    let current = root
    for (let depth = 2; depth <= length; depth += 1) {
      const child = { value: String(depth) }
      current.children = [child]
      current = child
    }
    return root
  }

  const accepted = mapTree(createChain(MAX_XMIND_MINDMAP_DEPTH))
  let current = accepted
  let depth = 1
  while (current.children.length > 0) {
    current = current.children[0]
    depth += 1
  }
  assert.equal(depth, MAX_XMIND_MINDMAP_DEPTH)
  assert.throws(
    () => mapTree(createChain(MAX_XMIND_MINDMAP_DEPTH + 1)),
    /脑图层级不能超过 256/
  )
})

test('XMind 迭代映射拒绝循环、共享节点和损坏子节点', () => {
  const cycle = { value: 'cycle', children: [] }
  cycle.children.push(cycle)
  assert.throws(() => mapTree(cycle), /循环或重复引用/)

  const shared = { value: 'shared' }
  assert.throws(
    () => mapTree({ value: 'root', children: [shared, shared] }),
    /循环或重复引用/
  )
  assert.throws(
    () => mapTree({ value: 'root', children: [null] }),
    /节点格式无效/
  )
  assert.throws(
    () => mapTree({ value: 'root', children: {} }),
    /子节点格式无效/
  )
})

test('旧版 XMind 根节点查找保持当前层优先并安全跳过循环元素数组', () => {
  const nestedTopic = { name: 'topic', id: 'nested' }
  const directTopic = { name: 'topic', id: 'direct' }
  const rootList = [
    { name: 'sheet', elements: [{ name: 'wrapper', elements: [nestedTopic] }] },
    directTopic
  ]
  rootList[0].elements.push({ name: 'cycle', elements: rootList })

  assert.equal(
    findFirstXmindElementByName(rootList, 'topic'),
    directTopic
  )
  assert.equal(findFirstXmindElementByName(rootList, 'missing'), null)
  assert.equal(findFirstXmindElementByName(null, 'topic'), null)
})

test('XMind 三条转换链共用迭代映射且根节点图片写入 topic', async () => {
  const [source, backendCodecSource] = await Promise.all([
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/parse/xmind.js',
        import.meta.url
      ),
      'utf8'
    ),
    readFile(
      new URL(
        '../../../../ruoyi-fastapi-backend/module_mindmap/service/simple_mind_document_codec.py',
        import.meta.url
      ),
      'utf8'
    )
  ])

  assert.equal((source.match(/mapXmindTreeIterative\(\{/g) || []).length, 3)
  assert.doesNotMatch(source, /const walk = (?:async )?\(/)
  assert.doesNotMatch(source, /let walk = (?:async )?\(/)
  assert.match(
    source,
    /handleNodeImageToXmind\(\s*node,\s*newData,\s*waitLoadImageList,\s*imageList\s*\)/
  )
  assert.match(
    source,
    /zip\.file\('content\.json', stringifyJsonValueIterative\(contentData\)\)/
  )
  assert.doesNotMatch(source, /JSON\.stringify\(contentData\)/)
  assert.match(backendCodecSource, /MAX_NODE_COUNT\s*=\s*20_000/)
  assert.match(backendCodecSource, /MAX_TREE_DEPTH\s*=\s*256/)
})
