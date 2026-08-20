import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  cloneJsonValueIterative,
  stringifyJsonValueIterative,
} from '../../libs/simple-mind-map/src/utils/jsonClone.js'

test('iterative JSON clone preserves document primitives and isolation', () => {
  const source = {
    text: 'root',
    count: 2,
    enabled: true,
    empty: null,
    nested: { list: [1, 'two', false] },
  }
  const cloned = cloneJsonValueIterative(source)
  assert.deepEqual(cloned, source)
  assert.notEqual(cloned, source)
  assert.notEqual(cloned.nested, source.nested)
  assert.notEqual(cloned.nested.list, source.nested.list)
})

test('iterative JSON clone matches omitted, array-null and numeric normalization semantics', () => {
  const source = {
    omitted: undefined,
    fn() {},
    symbol: Symbol('ignored'),
    nan: Number.NaN,
    infinity: Infinity,
    negativeZero: -0,
    list: [undefined, () => {}, Symbol('ignored'), Number.NaN, -0],
  }
  assert.deepEqual(cloneJsonValueIterative(source), {
    nan: null,
    infinity: null,
    negativeZero: 0,
    list: [null, null, null, null, 0],
  })
  assert.equal(cloneJsonValueIterative(undefined), null)
  assert.equal(cloneJsonValueIterative(1n), null)
})

test('iterative JSON clone applies toJSON and preserves dangerous keys as data', () => {
  const source = JSON.parse('{"__proto__":{"polluted":true},"constructor":"data"}')
  source.when = new Date('2026-08-19T00:00:00.000Z')
  const cloned = cloneJsonValueIterative(source)
  assert.equal(Object.prototype.polluted, undefined)
  assert.equal(Object.hasOwn(cloned, '__proto__'), true)
  assert.deepEqual(cloned.__proto__, { polluted: true })
  assert.equal(cloned.constructor, 'data')
  assert.equal(cloned.when, '2026-08-19T00:00:00.000Z')
})

test('iterative JSON clone rejects cycles but duplicates shared values like JSON', () => {
  const cycle = {}
  cycle.self = cycle
  assert.equal(cloneJsonValueIterative(cycle), null)

  const shared = { value: 1 }
  const cloned = cloneJsonValueIterative({ left: shared, right: shared })
  assert.deepEqual(cloned, { left: { value: 1 }, right: { value: 1 } })
  assert.notEqual(cloned.left, cloned.right)
})

test('iterative JSON clone handles a 20,000-level document without recursion', () => {
  const source = { value: 0 }
  let current = source
  for (let depth = 1; depth < 20_000; depth += 1) {
    current.child = { value: depth }
    current = current.child
  }

  const cloned = cloneJsonValueIterative(source)
  current = cloned
  let depth = 1
  while (current.child) {
    current = current.child
    depth += 1
  }
  assert.equal(depth, 20_000)
  assert.equal(current.value, 19_999)
})

test('simpleDeepClone delegates to the iterative JSON clone', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/utils/index.js', import.meta.url),
    'utf8'
  )
  assert.match(source, /import \{[\s\S]*cloneJsonValueIterative,[\s\S]*stringifyJsonValueIterative[\s\S]*\} from '\.\/jsonClone'/)
  assert.match(source, /export const simpleDeepClone = data => \{\s*return cloneJsonValueIterative\(data\)\s*\}/)
  assert.doesNotMatch(source, /JSON\.parse\(JSON\.stringify\(data\)\)/)
})

test('iterative JSON stringify matches native document serialization semantics', () => {
  const value = {
    text: 'line\n"quoted"',
    omitted: undefined,
    nan: Number.NaN,
    negativeZero: -0,
    list: [1, undefined, Infinity, '四'],
    nested: { enabled: true, empty: null },
    when: new Date('2026-08-19T00:00:00.000Z'),
    boxed: [new Number(2), new String('text'), new Boolean(false)],
  }
  assert.equal(stringifyJsonValueIterative(value), JSON.stringify(value))
  assert.equal(stringifyJsonValueIterative(undefined), undefined)
})

test('iterative JSON stringify handles omission after toJSON without malformed commas', () => {
  const omitted = { toJSON: () => undefined }
  const value = {
    first: 1,
    omitted,
    last: 2,
    list: [omitted, 3],
  }
  assert.equal(stringifyJsonValueIterative(value), JSON.stringify(value))
})

test('iterative JSON stringify matches native numeric and string indentation', () => {
  const value = {
    first: 1,
    nested: { enabled: true, omitted: undefined },
    list: [null, { text: '节点' }],
    empty: {},
  }
  for (const space of [2, 20, '--', new Number(3), new String('abcdefghijk')]) {
    assert.equal(
      stringifyJsonValueIterative(value, space),
      JSON.stringify(value, null, space),
    )
  }
})

test('iterative JSON stringify rejects cycles and BigInt like native JSON', () => {
  const cycle = { value: 1 }
  cycle.self = cycle
  assert.throws(() => stringifyJsonValueIterative(cycle), /Cyclic JSON value/)
  assert.throws(() => stringifyJsonValueIterative({ value: 1n }), /BigInt/)
})

test('iterative JSON stringify serializes a 20,000-level document without recursion', () => {
  const root = { value: 0 }
  let current = root
  for (let depth = 1; depth < 20_000; depth += 1) {
    current.child = { value: depth }
    current = current.child
  }
  const serialized = stringifyJsonValueIterative(root)
  assert.equal(serialized.startsWith('{"value":0,"child":'), true)
  assert.equal(serialized.endsWith('}'.repeat(20_000)), true)
  assert.equal((serialized.match(/"value":/g) || []).length, 20_000)
})

test('all document serialization and node comparison paths share stack-safe boundaries', async () => {
  const [
    command,
    exporter,
    utils,
    xmind,
    contextmenu,
    draft,
    backup,
    crossNode,
    layoutBase,
    mindMapNode,
    yjsTreeState,
  ] = await Promise.all([
    readFile(new URL('../../libs/simple-mind-map/src/core/command/Command.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/plugins/Export.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/utils/index.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/parse/xmind.js', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Contextmenu.vue', import.meta.url), 'utf8'),
    readFile(new URL('../mindmap-draft.js', import.meta.url), 'utf8'),
    readFile(new URL('../mindmap-backup.js', import.meta.url), 'utf8'),
    readFile(new URL('../yjs-cross-node-state.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/layouts/Base.js', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/src/core/render/node/MindMapNode.js', import.meta.url), 'utf8'),
    readFile(new URL('../yjs-tree-state.js', import.meta.url), 'utf8'),
  ])
  assert.match(command, /const dataStr = stringifyJsonValueIterative\(data\)/)
  assert.doesNotMatch(command, /removeDataUid\(/)
  assert.match(exporter, /const str = stringifyJsonValueIterative\(data\)/)
  assert.match(utils, /writeText\(stringifyJsonValueIterative\(data\)\)/)
  assert.match(xmind, /zip\.file\('content\.json', stringifyJsonValueIterative\(contentData\)\)/)
  assert.match(contextmenu, /str = stringifyJsonValueIterative\(data\)/)
  assert.match(draft, /const cloned = cloneJsonValueIterative\(normalized\)/)
  assert.match(draft, /const serialized = stringifyJsonValueIterative\(record\)/)
  assert.match(backup, /stringifyJsonValueIterative\(document, 2\)/)
  assert.match(crossNode, /const cloned = cloneJsonValueIterative\(value\)/)
  assert.match(layoutBase, /stringifyJsonValueIterative\(newNode\.getData\(\)\)/)
  assert.match(mindMapNode, /this\.nodeDataSnapshot = stringifyJsonValueIterative\(this\.getData\(\)\)/)
  assert.match(utils, /if \(!isSameObjectValue\(oldVal, newVal\)\)/)
  assert.match(yjsTreeState, /return isSameObject\(left, right\)/)
  assert.doesNotMatch(layoutBase, /JSON\.stringify/)
  assert.doesNotMatch(mindMapNode, /JSON\.stringify/)
  assert.doesNotMatch(yjsTreeState, /JSON\.stringify/)
})
