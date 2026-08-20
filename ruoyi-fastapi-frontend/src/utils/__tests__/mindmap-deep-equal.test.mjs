import assert from 'node:assert/strict'
import test from 'node:test'

import { isSameObject } from '../../libs/simple-mind-map/src/utils/deepEqual.js'

test('deep equality preserves object and array comparison semantics', () => {
  const left = {
    data: { uid: 'root', text: 'Root' },
    children: [{ uid: 'left' }, { uid: 'right' }]
  }
  const reordered = {
    children: [{ uid: 'left' }, { uid: 'right' }],
    data: { text: 'Root', uid: 'root' }
  }

  assert.equal(isSameObject(left, reordered), true)
  reordered.children.reverse()
  assert.equal(isSameObject(left, reordered), false)
  assert.equal(isSameObject({ value: undefined }, {}), false)

  const dangerousLeft = JSON.parse(
    '{"__proto__":{"safe":true},"constructor":"node"}'
  )
  const dangerousRight = JSON.parse(
    '{"constructor":"node","__proto__":{"safe":true}}'
  )
  assert.equal(isSameObject(dangerousLeft, dangerousRight), true)
  dangerousRight['__proto__'].safe = false
  assert.equal(isSameObject(dangerousLeft, dangerousRight), false)
})

test('deep equality retains strict equality for non-container values', () => {
  const date = new Date(0)
  assert.equal(isSameObject('1', 1), false)
  assert.equal(isSameObject(Number.NaN, Number.NaN), false)
  assert.equal(isSameObject(date, date), true)
  assert.equal(isSameObject(date, new Date(0)), false)
})

test('deep equality terminates equivalent and different cyclic graphs', () => {
  const left = { uid: 'root', children: [] }
  const right = { uid: 'root', children: [] }
  left.children.push(left)
  right.children.push(right)
  assert.equal(isSameObject(left, right), true)

  const different = { uid: 'root', children: [{ uid: 'leaf', children: [] }] }
  assert.equal(isSameObject(left, different), false)
})

test('deep equality compares a 20,000-key collaboration map linearly', () => {
  const left = {}
  const right = {}
  for (let index = 0; index < 20_000; index += 1) {
    const uid = `node-${index}`
    left[uid] = { data: { uid, text: String(index) }, children: [] }
    right[uid] = { children: [], data: { text: String(index), uid } }
  }

  assert.equal(isSameObject(left, right), true)
  right['node-19999'].data.text = 'changed'
  assert.equal(isSameObject(left, right), false)
})

test('deep equality compares a 20,000-level object without the call stack', () => {
  const left = { value: 0 }
  const right = { value: 0 }
  let leftCurrent = left
  let rightCurrent = right
  for (let index = 1; index < 20_000; index += 1) {
    leftCurrent.child = { value: index }
    rightCurrent.child = { value: index }
    leftCurrent = leftCurrent.child
    rightCurrent = rightCurrent.child
  }

  assert.equal(isSameObject(left, right), true)
  rightCurrent.value = -1
  assert.equal(isSameObject(left, right), false)
})
