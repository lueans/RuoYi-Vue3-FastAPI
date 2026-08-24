import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { selectLargestFittingToolbarCount } from '../mindmap-toolbar-layout.js'

const toolbarSourceUrl = new URL('../../components/MindMap/Toolbar.vue', import.meta.url)

test('工具栏选择真实可容纳的最大候选并支持最终候选宽度回落', () => {
  assert.equal(selectLargestFittingToolbarCount([180, 220, 260, 240], 245), 3)
  assert.equal(selectLargestFittingToolbarCount([180, 220, 260], 230), 1)
  assert.equal(selectLargestFittingToolbarCount([180, 220], 100), 0)
})

test('工具栏布局选择拒绝非法测量值和容器宽度', () => {
  assert.equal(selectLargestFittingToolbarCount([100, Number.NaN, 140], 150), 2)
  assert.equal(selectLargestFittingToolbarCount([100, -1, Number.POSITIVE_INFINITY], 150), 0)
  assert.equal(selectLargestFittingToolbarCount(null, 150), 0)
  assert.equal(selectLargestFittingToolbarCount([100], Number.NaN), 0)
})

test('工具栏用容器尺寸和最新请求驱动真实候选测量', async () => {
  const source = await readFile(toolbarSourceUrl, 'utf8')

  assert.match(source, /ref="toolbarContainerRef"/)
  assert.match(source, /new ResizeObserver\(scheduleToolbarLayout\)/)
  assert.match(source, /toolbarResizeObserver\.observe\(toolbarContainerRef\.value\)/)
  assert.match(source, /const requestId = toolbarLayoutRequests\.begin\(\)/)
  assert.match(source, /isToolbarLayoutCurrent\(requestId, toolbar\)/)
  assert.match(source, /const maxVisibleCount = props\.embedded \? Math\.min\(8, all\.length\) : all\.length/)
  assert.match(source, /candidateCount = 0; candidateCount <= maxVisibleCount/)
  assert.match(source, /showMoreBtn\.value = candidateCount < all\.length/)
  assert.match(source, /await nextTick\(\)[\s\S]*candidateWidths\.push\(measureToolbarWidth\(toolbar\)\)/)
  assert.match(source, /selectLargestFittingToolbarCount\(candidateWidths, containerWidth\)/)
})

test('工具栏卸载会取消布局任务并释放尺寸观察器', async () => {
  const source = await readFile(toolbarSourceUrl, 'utf8')

  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*componentAlive = false/)
  assert.match(source, /toolbarLayoutRequests\.invalidate\(\)/)
  assert.match(source, /toolbarResizeObserver\?\.disconnect\(\)/)
  assert.match(source, /clearTimeout\(computeThrottleTimer\)/)
})
