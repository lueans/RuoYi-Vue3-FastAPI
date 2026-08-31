import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMindmapTagSelectionIndex,
  getMindmapTagSelectionMode,
  hasMindmapManagedTag,
  normalizeMindmapSingleSelectionTags,
  removeMindmapSingleSelectionPeers,
} from '../mindmap-tag-selection.js'

const categories = [
  { id: 10, selectionMode: 'single' },
  { id: 20, selectionMode: 'multiple' },
]
const catalog = [
  { id: 1, categoryId: 10 },
  { id: 2, categoryId: 10 },
  { id: 3, categoryId: 20 },
  { id: 4, categoryId: 20 },
]
const index = buildMindmapTagSelectionIndex(categories, catalog)

test('单选分组会移除同组旧标签但保留其他分组', () => {
  const current = [{ tagId: 1 }, { tagId: 3 }, '历史文本标签']

  assert.deepEqual(
    removeMindmapSingleSelectionPeers(current, { id: 2, categoryId: 10 }, index),
    [{ tagId: 3 }, '历史文本标签'],
  )
  assert.equal(getMindmapTagSelectionMode({ id: 2, categoryId: 10 }, index), 'single')
})

test('节点自带分组身份时不依赖当前用户能否读取标签目录', () => {
  const collaboratorIndex = buildMindmapTagSelectionIndex(categories, [
    { id: 2, categoryId: 10 },
  ])
  const hiddenOwnerTag = { tagId: 1, categoryId: 10 }

  assert.deepEqual(
    removeMindmapSingleSelectionPeers(
      [hiddenOwnerTag, { tagId: 3, categoryId: 20 }],
      { id: 2, categoryId: 10 },
      collaboratorIndex,
    ),
    [{ tagId: 3, categoryId: 20 }],
  )
})

test('多选分组不会移除已选标签', () => {
  const current = [{ tagId: 1 }, { tagId: 3 }]

  assert.deepEqual(
    removeMindmapSingleSelectionPeers(current, { id: 4, categoryId: 20 }, index),
    current,
  )
  assert.equal(getMindmapTagSelectionMode({ id: 4, categoryId: 20 }, index), 'multiple')
  assert.equal(hasMindmapManagedTag(current, { id: 3 }), true)
  assert.equal(hasMindmapManagedTag(current, { id: 4 }), false)
})

test('提交时每个单选分组保留最后选择的标签', () => {
  const current = [
    { tagId: 1 },
    { tagId: 3 },
    { tagId: 2 },
    { tagId: 4 },
  ]

  assert.deepEqual(normalizeMindmapSingleSelectionTags(current, index), [
    { tagId: 3 },
    { tagId: 2 },
    { tagId: 4 },
  ])
})
