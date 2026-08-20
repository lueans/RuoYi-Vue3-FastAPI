import assert from 'node:assert/strict'
import test from 'node:test'

import {
  estimateHistoryEntryBytes,
  trimHistoryEntries
} from '../../libs/simple-mind-map/src/utils/historyBuffer.js'

test('history buffer evicts oldest snapshots by count', () => {
  const history = ['one', 'two', 'three', 'four']

  const result = trimHistoryEntries(history, 2, Infinity)

  assert.equal(result, history)
  assert.deepEqual(history, ['three', 'four'])
})

test('history buffer applies a conservative byte budget and keeps newest data', () => {
  const history = ['1234', '5678', 'abcdefghij']
  assert.equal(estimateHistoryEntryBytes(history[0]), 8)

  trimHistoryEntries(history, 500, 24)

  assert.deepEqual(history, ['abcdefghij'])
})

test('history buffer always retains an oversized latest snapshot', () => {
  const history = ['old', 'a'.repeat(100)]

  trimHistoryEntries(history, 500, 10)

  assert.deepEqual(history, ['a'.repeat(100)])
  assert.deepEqual(trimHistoryEntries([], 1, 1), [])

  const zeroCount = ['old', 'latest']
  trimHistoryEntries(zeroCount, 0, Infinity)
  assert.deepEqual(zeroCount, ['latest'])
})
