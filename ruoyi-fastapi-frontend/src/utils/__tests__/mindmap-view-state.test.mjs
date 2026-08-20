import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  calculateViewFit,
  calculateViewScaleAroundPoint,
  normalizeViewCoordinate,
  normalizeViewScale,
  normalizeViewTransformData
} from '../../libs/simple-mind-map/src/utils/viewState.js'

test('现代视图状态只恢复白名单字段并生成规范 SVG 变换', () => {
  const normalized = normalizeViewTransformData({
    state: {
      scale: 1.5,
      x: 24,
      y: -12,
      sx: 20,
      sy: -10,
      mindMap: 'must-not-restore',
      setScale: 'must-not-restore'
    },
    transform: {
      rotate: 45,
      skew: 10
    }
  })

  assert.deepEqual(normalized, {
    state: { scale: 1.5, x: 24, y: -12, sx: 20, sy: -10 },
    transform: {
      origin: [0, 0],
      scale: 1.5,
      translate: [24, -12]
    }
  })
  assert.equal(Object.hasOwn(normalized.state, 'mindMap'), false)
  assert.equal(Object.hasOwn(normalized.transform, 'rotate'), false)
})

test('旧 transform-only 视图可恢复且非法字段回退到安全状态', () => {
  assert.deepEqual(
    normalizeViewTransformData({
      transform: {
        scaleX: 1.25,
        scaleY: 1.25,
        translateX: 30,
        translateY: -15
      }
    }),
    {
      state: { scale: 1.25, x: 30, y: -15, sx: 30, sy: -15 },
      transform: {
        origin: [0, 0],
        scale: 1.25,
        translate: [30, -15]
      }
    }
  )

  assert.deepEqual(
    normalizeViewTransformData(
      {
        state: { scale: 0, x: Infinity, y: Number.NaN },
        transform: { scaleX: -2, translateX: 'bad' }
      },
      { scale: 2, x: 8, y: 9 }
    ).state,
    { scale: 2, x: 8, y: 9, sx: 8, sy: 9 }
  )
  assert.equal(normalizeViewTransformData(null), null)
})

test('缩放和坐标规范化拒绝非正比例并兼容有限数字字符串', () => {
  assert.equal(normalizeViewScale(2), 2)
  assert.equal(normalizeViewScale('1.25'), 1.25)
  assert.equal(normalizeViewScale(0), null)
  assert.equal(normalizeViewScale(-1, 3), 3)
  assert.equal(normalizeViewScale(Infinity, 0), null)
  assert.equal(normalizeViewCoordinate('12.5'), 12.5)
  assert.equal(normalizeViewCoordinate(Number.NaN, 7), 7)
})

test('围绕指定中心缩放保持中心下的画布坐标不漂移', () => {
  const current = { scale: 1, x: 20, y: 10 }
  const next = calculateViewScaleAroundPoint(current, 2, { x: 100, y: 50 })

  assert.deepEqual(next, { scale: 2, x: -60, y: -30 })
  assert.equal(
    (100 - current.x) / current.scale,
    (100 - next.x) / next.scale
  )
  assert.equal(
    (50 - current.y) / current.scale,
    (50 - next.y) / next.scale
  )
  assert.equal(calculateViewScaleAroundPoint(current, 0, { x: 0, y: 0 }), null)
})

test('适应画布在无需放大时恢复 100% 并居中内容', () => {
  const fit = calculateViewFit({
    contentRect: { x: 60, y: 60, width: 200, height: 100 },
    viewportRect: { left: 10, top: 20, width: 1000, height: 600 },
    transform: { scaleX: 1, scaleY: 1, translateX: 0, translateY: 0 },
    state: { scale: 1, x: 0, y: 0 },
    padding: 20,
    enlarge: false
  })

  assert.equal(fit.scale, 1)
  assert.equal(fit.offsetX, 350)
  assert.equal(fit.offsetY, 210)
  assert.equal(fit.availableWidth, 960)
  assert.equal(fit.availableHeight, 560)
})

test('适应画布可按比例放大或缩小并保持长宽比', () => {
  const enlarged = calculateViewFit({
    contentRect: { x: 50, y: 40, width: 200, height: 100 },
    viewportRect: { left: 0, top: 0, width: 1000, height: 600 },
    transform: { scaleX: 1, scaleY: 1, translateX: 0, translateY: 0 },
    state: { scale: 1, x: 0, y: 0 },
    padding: 20,
    enlarge: true
  })
  const reduced = calculateViewFit({
    contentRect: { x: 50, y: 40, width: 2000, height: 1000 },
    viewportRect: { left: 0, top: 0, width: 1000, height: 600 },
    transform: { scaleX: 1, scaleY: 1, translateX: 0, translateY: 0 },
    state: { scale: 1, x: 0, y: 0 },
    padding: 20
  })

  assert.equal(enlarged.scale, 4.8)
  assert.ok(Math.abs(enlarged.offsetX - (-220)) < 1e-9)
  assert.ok(Math.abs(enlarged.offsetY - (-132)) < 1e-9)
  assert.equal(reduced.scale, 0.48)
  assert.ok(Math.abs(reduced.offsetX - (-4)) < 1e-9)
  assert.ok(Math.abs(reduced.offsetY - 40.8) < 1e-9)
})

test('适应画布限制过大边距并拒绝零尺寸或非法变换', () => {
  const narrow = calculateViewFit({
    contentRect: { x: 10, y: 10, width: 20, height: 20 },
    viewportRect: { left: 0, top: 0, width: 100, height: 60 },
    transform: { scaleX: 1, scaleY: 1, translateX: 0, translateY: 0 },
    state: { scale: 1, x: 0, y: 0 },
    padding: 100
  })

  assert.equal(narrow.padding, 29.5)
  assert.equal(narrow.availableHeight, 1)
  assert.equal(narrow.scale, 0.05)
  assert.equal(calculateViewFit({
    contentRect: { x: 0, y: 0, width: 0, height: 10 },
    viewportRect: { width: 100, height: 100 },
    transform: { scaleX: 1, scaleY: 1 }
  }), null)
  assert.equal(calculateViewFit({
    contentRect: { x: 0, y: 0, width: 10, height: 10 },
    viewportRect: { width: 100, height: 100 },
    transform: { scaleX: 0, scaleY: 1 }
  }), null)
  assert.equal(calculateViewFit(), null)
})

test('View 恢复和公共缩放入口统一使用安全规范化边界', async () => {
  const source = await readFile(
    new URL(
      '../../libs/simple-mind-map/src/core/view/View.js',
      import.meta.url
    ),
    'utf8'
  )

  assert.match(source, /normalizeViewTransformData\(viewData, this\)/)
  assert.match(source, /calculateViewScaleAroundPoint\(/)
  assert.match(source, /const fit = calculateViewFit\(/)
  assert.match(source, /const nextScale = normalizeViewScale\(scale\)/)
  assert.doesNotMatch(source, /Object\.keys\(viewData\.state\)/)
  assert.doesNotMatch(source, /const newRect = getRbox\(\) \|\| draw\.rbox\(\)/)
})
