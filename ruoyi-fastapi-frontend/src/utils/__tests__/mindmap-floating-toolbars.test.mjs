import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getCommonNodeIcons,
  removeNodeIconType,
  toggleNodeIcon,
  toggleNodeIconAcrossLists,
} from '../mindmap-node-icon.js'

test('节点图标切换保持每类唯一且再次选择会取消', () => {
  const replaced = toggleNodeIcon(['priority_1', 'progress_2'], 'priority', '3')
  assert.deepEqual(replaced, {
    list: ['priority_3', 'progress_2'],
    selected: true,
  })

  const removed = toggleNodeIcon(replaced.list, 'priority', '3')
  assert.deepEqual(removed, {
    list: ['progress_2'],
    selected: false,
  })
})

test('移除图标按类别删除而不会把刚取消的图标重新添加', () => {
  assert.deepEqual(
    removeNodeIconType(['priority_2', 'progress_4', 'priority_2', null], 'priority'),
    ['progress_4'],
  )
})

test('多选节点的图标切换会统一状态而不是让选择继续分裂', () => {
  const unified = toggleNodeIconAcrossLists(
    [['priority_1'], ['progress_2'], ['priority_1', 'progress_2']],
    'priority',
    '1',
  )
  assert.equal(unified.selected, true)
  assert.deepEqual(unified.lists, [
    ['priority_1'],
    ['progress_2', 'priority_1'],
    ['priority_1', 'progress_2'],
  ])
  assert.deepEqual(getCommonNodeIcons(unified.lists), ['priority_1'])

  const removed = toggleNodeIconAcrossLists(unified.lists, 'priority', '1')
  assert.equal(removed.selected, false)
  assert.deepEqual(removed.lists, [[], ['progress_2'], ['progress_2']])
})

test('图片位置与节点图标浮动工具条使用可聚焦控件和显式状态', async () => {
  const [imageSource, iconSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/NodeImgPlacementToolbar.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/NodeIconToolbar.vue', import.meta.url), 'utf8'),
  ])

  assert.match(imageSource, /role="toolbar"[\s\S]*aria-label="节点图片位置"/)
  assert.match(imageSource, /:aria-pressed="currentPlacement === item\.value"/)
  assert.doesNotMatch(imageSource, /class="btn iconfont icontupianweizhi"/)
  assert.match(iconSource, /:aria-label="iconGroupName \|\| '节点图标'"/)
  assert.match(iconSource, /:aria-pressed="nodeIconList\.includes/)
  assert.match(iconSource, /aria-label="移除当前节点图标"/)
  assert.match(iconSource, /activeNodes\[0\] !== currentNode/)
  assert.match(iconSource, /:class="\{ isDark \}"/)
})
