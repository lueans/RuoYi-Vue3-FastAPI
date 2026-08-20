import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  calculateMindmapWheelScale,
  clampMindmapScale,
  getMindmapScaleBounds,
  normalizeMindmapWheelDelta,
  shouldZoomMindmapWheel,
} from '../mindmap-zoom.js'
import {
  isLikelyTouchpadWheel,
  resolveWheelZoomDirection,
} from '../../libs/simple-mind-map/src/utils/wheel.js'

test('手动输入与滚轮缩放共享编辑器配置边界', () => {
  const options = { minZoomRatio: 25, maxZoomRatio: 250 }

  assert.equal(clampMindmapScale(0.01, options), 0.25)
  assert.equal(clampMindmapScale(1.5, options), 1.5)
  assert.equal(clampMindmapScale(8, options), 2.5)
})

test('无限上限和异常缩放配置具有稳定回退行为', () => {
  assert.equal(clampMindmapScale(12, { minZoomRatio: 10, maxZoomRatio: -1 }), 12)
  assert.deepEqual(getMindmapScaleBounds({ minZoomRatio: 'bad', maxZoomRatio: 5 }), {
    minScale: 0.2,
    maxScale: 0.2,
  })
  assert.equal(clampMindmapScale(Number.NaN), null)
})

test('滚轮设置控制缩放或平移，触控板缩放手势始终保持缩放', () => {
  assert.equal(shouldZoomMindmapWheel({}, { mousewheelAction: 'zoom' }), true)
  assert.equal(shouldZoomMindmapWheel({}, { mousewheelAction: 'move' }), false)
  assert.equal(shouldZoomMindmapWheel({ ctrlKey: true }, { mousewheelAction: 'move' }), true)
  assert.equal(shouldZoomMindmapWheel({ metaKey: true }, { mousewheelAction: 'move' }), true)
})

test('滚轮位移按模式归一化、限制单次幅度并支持横向设备', () => {
  assert.equal(normalizeMindmapWheelDelta({ deltaY: 4 }), 4)
  assert.equal(normalizeMindmapWheelDelta({ deltaY: 3, deltaMode: 1 }), 48)
  assert.equal(normalizeMindmapWheelDelta({ deltaY: -1, deltaMode: 2 }), -100)
  assert.equal(normalizeMindmapWheelDelta({ deltaY: 0, deltaX: 12 }), 12)
  assert.equal(normalizeMindmapWheelDelta({ deltaY: 10_000 }), 100)
  assert.equal(normalizeMindmapWheelDelta({ deltaY: Number.NaN }), 0)
})

test('鼠标与触控板缩放平滑、遵守方向反转并保持配置边界', () => {
  const options = {
    minZoomRatio: 20,
    maxZoomRatio: 400,
    mousewheelZoomActionReverse: true,
  }
  const mouseStep = calculateMindmapWheelScale(1, { deltaY: 100 }, options)
  const trackpadStep = calculateMindmapWheelScale(1, { deltaY: -2 }, options)

  assert.ok(mouseStep > 0.8 && mouseStep < 1)
  assert.ok(trackpadStep > 1 && trackpadStep < 1.01)
  assert.ok(
    calculateMindmapWheelScale(1, { deltaY: 100 }, {
      ...options,
      mousewheelZoomActionReverse: false,
    }) > 1
  )
  assert.equal(calculateMindmapWheelScale(0.2, { deltaY: 100 }, options), 0.2)
  assert.equal(calculateMindmapWheelScale(4, { deltaY: -100 }, options), 4)
  assert.equal(calculateMindmapWheelScale(0, { deltaY: 1 }, options), null)
})

test('默认视图缩放识别上下左右并保持纵向优先', () => {
  assert.equal(resolveWheelZoomDirection(['up']), -1)
  assert.equal(resolveWheelZoomDirection(['left']), -1)
  assert.equal(resolveWheelZoomDirection(['down']), 1)
  assert.equal(resolveWheelZoomDirection(['right']), 1)
  assert.equal(resolveWheelZoomDirection(['up', 'right']), -1)
  assert.equal(resolveWheelZoomDirection(['down', 'left']), 1)
  assert.equal(resolveWheelZoomDirection([]), 0)
})

test('触控板判定使用两个轴并排除零位移及离散滚轮模式', () => {
  assert.equal(isLikelyTouchpadWheel({ deltaX: 0, deltaY: 0 }), false)
  assert.equal(isLikelyTouchpadWheel({ deltaX: 4, deltaY: 7 }), true)
  assert.equal(isLikelyTouchpadWheel({ deltaX: 100, deltaY: 0 }), false)
  assert.equal(isLikelyTouchpadWheel({ deltaX: 0, deltaY: -100 }), false)
  assert.equal(isLikelyTouchpadWheel({ deltaY: 1, deltaMode: 1 }), false)
  assert.equal(isLikelyTouchpadWheel({ deltaY: 1, deltaMode: 2 }), false)
  assert.equal(isLikelyTouchpadWheel({ deltaY: Number.NaN }), false)
})

test('横向鼠标事件不会被触控板过滤且仍可解析缩放方向', () => {
  const event = { deltaX: -100, deltaY: 0, deltaMode: 0 }
  const isTouchPad = isLikelyTouchpadWheel(event)
  const dirs = event.deltaX < 0 ? ['left'] : ['right']

  assert.equal(isTouchPad, false)
  assert.equal(resolveWheelZoomDirection(dirs), -1)
})

test('编辑器只通过 View 发布缩放事件且默认视图使用方向解析器', async () => {
  const [editorSource, viewSource, eventSource] = await Promise.all([
    readFile(
      new URL('../../components/MindMap/Edit.vue', import.meta.url),
      'utf8'
    ),
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/core/view/View.js',
        import.meta.url
      ),
      'utf8'
    ),
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/core/event/Event.js',
        import.meta.url
      ),
      'utf8'
    )
  ])

  assert.match(editorSource, /calculateMindmapWheelScale\(/)
  assert.doesNotMatch(editorSource, /mm\.emit\('scale', mm\.view\.scale\)/)
  assert.match(viewSource, /resolveWheelZoomDirection\(dirs\)/)
  assert.doesNotMatch(viewSource, /DIR\.UP \|\| CONSTANTS\.DIR\.LEFT/)
  assert.match(eventSource, /isLikelyTouchpadWheel\(e\)/)
  assert.doesNotMatch(eventSource, /Math\.abs\(e\.deltaY\) <= 10/)
})
