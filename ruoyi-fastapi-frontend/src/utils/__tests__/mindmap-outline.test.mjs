import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  flattenMindmapOutline,
  MINDMAP_OUTLINE_ITEM_HEIGHT,
  resolveMindmapOutlineNavigation,
  resolveMindmapOutlineWindow,
} from '../mindmap-outline.js'

function node(uid, text, children = []) {
  return { data: { uid, text }, children }
}

test('大纲显式栈保持先序层级、兄弟语义和折叠状态', () => {
  const root = node('root', '根节点', [
    node('a', 'A', [node('a-1', 'A1')]),
    node('b', 'B'),
  ])
  const expanded = flattenMindmapOutline(root)

  assert.deepEqual(expanded.map(item => item.uid), ['root', 'a', 'a-1', 'b'])
  assert.deepEqual(expanded.map(item => item.level), [0, 1, 2, 1])
  assert.deepEqual(expanded.map(item => item.positionInSet), [1, 1, 1, 2])
  assert.equal(expanded[1].parentKey, expanded[0].key)
  assert.equal(expanded[2].parentKey, expanded[1].key)

  const collapsed = flattenMindmapOutline(root, new Set([expanded[1].key]))
  assert.deepEqual(collapsed.map(item => item.uid), ['root', 'a', 'b'])
  assert.equal(collapsed[1].expanded, false)
})

test('大纲对重复标识、空标识、共享对象和循环旧数据确定终止', () => {
  const shared = node('', '共享')
  const root = node('duplicate', '根', [
    node('duplicate', '重复'),
    shared,
    shared,
  ])
  root.children.push(root)

  const result = flattenMindmapOutline(root)
  assert.equal(result.length, 3)
  assert.equal(new Set(result.map(item => item.key)).size, result.length)
  assert.equal(result[2].text, '共享')
})

test('大纲将富文本节点规范为可读纯文本', () => {
  const root = {
    data: {
      uid: 'root',
      richText: true,
      text: '<p><span>根&nbsp;节点</span><br>第二行 &amp; &#x8BA1;&#21010;</p>',
    },
    children: [
      { data: { uid: 'child', text: '<p><span>旧数据节点</span></p>' }, children: [] },
    ],
  }

  const outline = flattenMindmapOutline(root)
  assert.equal(outline[0].text, '根 节点 第二行 & 计划')
  assert.equal(outline[1].text, '旧数据节点')
})

test('二万层无标识大纲保持线性键空间且窗口渲染为常数级 DOM 数量', () => {
  const root = node('', '0')
  let current = root
  for (let index = 1; index < 20000; index += 1) {
    const child = node('', String(index))
    current.children = [child]
    current = child
  }

  const outline = flattenMindmapOutline(root)
  assert.equal(outline.length, 20000)
  assert.equal(outline.at(-1).level, 19999)
  assert.equal(new Set(outline.map(item => item.key)).size, 20000)

  const window = resolveMindmapOutlineWindow(
    outline,
    10000 * MINDMAP_OUTLINE_ITEM_HEIGHT,
    400,
  )
  assert.equal(window.totalHeight, 20000 * MINDMAP_OUTLINE_ITEM_HEIGHT)
  assert.equal(window.items.length <= 22, true)
  assert.equal(window.items[0].index < 10000, true)
  assert.equal(window.items.at(-1).index > 10000, true)
})

test('大纲键盘导航覆盖顺序、首尾、父子和折叠边界', () => {
  const items = flattenMindmapOutline(node('root', '根', [
    node('a', 'A', [node('a-1', 'A1')]),
    node('b', 'B'),
  ]))

  assert.deepEqual(resolveMindmapOutlineNavigation(items, items[1].key, 'ArrowDown'), { type: 'focus', index: 2 })
  assert.deepEqual(resolveMindmapOutlineNavigation(items, items[1].key, 'ArrowLeft'), { type: 'collapse', index: 1 })
  assert.deepEqual(resolveMindmapOutlineNavigation(items, items[2].key, 'ArrowLeft'), { type: 'focus', index: 1 })
  assert.deepEqual(resolveMindmapOutlineNavigation(items, items[1].key, 'ArrowRight'), { type: 'focus', index: 2 })
  assert.deepEqual(resolveMindmapOutlineNavigation(items, items[2].key, 'Home'), { type: 'focus', index: 0 })
  assert.deepEqual(resolveMindmapOutlineNavigation(items, items[2].key, 'End'), { type: 'focus', index: 3 })

  const collapsed = flattenMindmapOutline(node('root', '根', [node('a', 'A')]), new Set(['uid:root']))
  assert.deepEqual(resolveMindmapOutlineNavigation(collapsed, collapsed[0].key, 'ArrowRight'), { type: 'expand', index: 0 })
})

test('大纲侧栏使用窗口列表、尺寸观察器和漫游焦点契约', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/OutlineSidebar.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /v-for="entry in outlineWindow\.items"/)
  assert.doesNotMatch(source, /v-for="item in flatOutline"/)
  assert.match(source, /flattenMindmapOutline\(outlineData\.value, collapsedKeys\.value\)/)
  assert.match(source, /resolveMindmapOutlineWindow\(/)
  assert.match(source, /new ResizeObserver\(measureOutlineViewport\)/)
  assert.match(source, /role="tree"/)
  assert.match(source, /role="treeitem"/)
  assert.match(source, /:tabindex="tabbableKey === entry\.item\.key \? 0 : -1"/)
  assert.match(source, /visibleItems\.some\(entry => entry\.item\.key === focusedKey\.value\)/)
  assert.match(source, /resolveMindmapOutlineNavigation\(flatOutline\.value, item\.key, event\.key\)/)
  assert.match(source, /targetRefs\.get\(item\.key\)\?\.focus\?\.\(\{ preventScroll: true \}\)/)
  assert.match(source, /viewportResizeObserver\?\.disconnect\(\)/)
})
