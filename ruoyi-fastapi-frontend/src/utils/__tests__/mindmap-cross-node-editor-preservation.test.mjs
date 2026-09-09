import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

function extractMethod(source, signature, nextSignature) {
  const start = source.indexOf(`  ${signature} {`)
  const end = source.indexOf(`\n  ${nextSignature}`, start)
  assert.ok(start >= 0, `missing method: ${signature}`)
  assert.ok(end > start, `missing method boundary: ${nextSignature}`)
  const method = source.slice(start, end)
  const body = method.slice(method.indexOf('{') + 1, method.lastIndexOf('}'))
  const args = signature.slice(signature.indexOf('(') + 1, signature.lastIndexOf(')'))
  return { args, body }
}

function createRuntimeNode(uid, data = {}) {
  const value = { uid, ...data }
  return {
    getData(key) {
      return key ? value[key] : value
    },
  }
}

test('无关远端结构渲染后关联线编辑器按稳定端点重绑且不关闭', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/plugins/AssociativeLine.js', import.meta.url),
    'utf8',
  )
  const renderMethod = extractMethod(
    source,
    'renderAllLines()',
    'captureActiveLineTextEditForRender()',
  )
  const restoreMethod = extractMethod(
    source,
    'restoreActiveLineTextEditAfterRender(renderedLine)',
    'discardDetachedActiveLineTextEdit(snapshot)',
  )
  const renderAllLines = Function(
    'walk',
    `'use strict'; return function (${renderMethod.args}) {${renderMethod.body}}`,
  )((tree, parent, before) => {
    before(tree.source)
    before(tree.target)
  })
  const restoreActiveLineTextEditAfterRender = Function(
    `'use strict'; return function (${restoreMethod.args}) {${restoreMethod.body}}`,
  )()

  const sourceNode = createRuntimeNode('source', {
    associativeLineTargets: ['target'],
    associativeLinePoint: [{}],
  })
  const targetNode = createRuntimeNode('target')
  const renderedLine = {
    path: {},
    clickPath: { stroke() {} },
    markerPath: {},
    text: {},
    node: sourceNode,
    toNode: targetNode,
    startPoint: {},
    endPoint: {},
    controlPoints: [{}, {}],
  }
  let clearCount = 0
  let discardCount = 0
  let controlRenderCount = 0
  let positionUpdateCount = 0
  const context = {
    isNotRenderAllLines: false,
    activeLine: ['old-line'],
    captureActiveLineTextEditForRender: () => ({
      sourceUid: 'source',
      targetUid: 'target',
    }),
    clearActiveLine: () => { clearCount += 1 },
    removeAllLines() {},
    removeControls() {},
    discardDetachedActiveLineTextEdit: () => { discardCount += 1 },
    updateAllLinesPos: () => [{}, {}],
    drawLine: () => renderedLine,
    restoreActiveLineTextEditAfterRender,
    getStyleConfig: () => ({ associativeLineActiveColor: '#409eff' }),
    getText: () => '已保存文字',
    renderText() {},
    renderControls: () => { controlRenderCount += 1 },
    updateTextEditBoxPos: () => { positionUpdateCount += 1 },
    front() {},
    mindMap: {
      renderer: { root: { source: sourceNode, target: targetNode } },
      opt: { defaultAssociativeLineText: '关联线' },
    },
  }

  renderAllLines.call(context)
  assert.equal(clearCount, 0)
  assert.equal(discardCount, 0)
  assert.equal(context.activeLine[3], sourceNode)
  assert.equal(context.activeLine[4], targetNode)
  assert.equal(controlRenderCount, 1)
  assert.equal(positionUpdateCount, 1)
})

test('无关远端结构渲染后外框编辑器按分组成员重绑且不关闭', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/plugins/OuterFrame.js', import.meta.url),
    'utf8',
  )
  const renderMethod = extractMethod(
    source,
    'renderOuterFrames()',
    'captureActiveOuterFrameTextEditForRender()',
  )
  const matchMethod = extractMethod(
    source,
    'matchesActiveOuterFrameTextEdit(snapshot, nodeList)',
    'restoreActiveOuterFrameTextEditAfterRender(',
  )
  const restoreMethod = extractMethod(
    source,
    'restoreActiveOuterFrameTextEditAfterRender(el, node, range, textNode, identity)',
    'discardDetachedActiveOuterFrameTextEdit(snapshot)',
  )
  const renderOuterFrames = Function(
    'walk',
    'getNodeOuterFrameList',
    'getNodeListBoundingRect',
    `'use strict'; return function (${renderMethod.args}) {${renderMethod.body}}`,
  )(
    (tree, parent, before) => before(tree.parent),
    parent => parent.frames,
    () => ({ left: 10, top: 20, width: 100, height: 40 }),
  )
  const matchesActiveOuterFrameTextEdit = Function(
    `'use strict'; return function (${matchMethod.args}) {${matchMethod.body}}`,
  )()
  const restoreActiveOuterFrameTextEditAfterRender = Function(
    `'use strict'; return function (${restoreMethod.args}) {${restoreMethod.body}}`,
  )()

  const firstMember = createRuntimeNode('member-a', {
    outerFrame: { groupId: 'frame-1', text: '已保存文字' },
  })
  const secondMember = createRuntimeNode('member-b', {
    outerFrame: { groupId: 'frame-1', text: '已保存文字' },
  })
  const parent = {
    frames: [{ nodeList: [firstMember, secondMember], range: [0, 1] }],
  }
  const frameElement = {
    stroke() {},
    on() {},
  }
  const textNode = {}
  let clearCount = 0
  let discardCount = 0
  let positionUpdateCount = 0
  const context = {
    isNotRenderOuterFrames: false,
    activeOuterFrame: { old: true },
    textNodeList: [],
    captureActiveOuterFrameTextEditForRender: () => ({
      groupId: 'frame-1',
      memberUids: ['member-a', 'member-b'],
    }),
    clearActiveOuterFrame: () => { clearCount += 1 },
    clearTextNodes() {},
    clearOuterFrameElList() {},
    discardDetachedActiveOuterFrameTextEdit: () => { discardCount += 1 },
    createOuterFrameEl: () => frameElement,
    getStyle: () => ({}),
    createText: () => textNode,
    getText: () => '已保存文字',
    renderText() {},
    matchesActiveOuterFrameTextEdit,
    restoreActiveOuterFrameTextEditAfterRender,
    getNodeRangeFirstNode: () => firstMember,
    updateTextEditBoxPos: () => { positionUpdateCount += 1 },
    setActiveOuterFrame() {},
    mindMap: {
      renderer: { root: { parent } },
      draw: { transform: () => ({ translateX: 0, translateY: 0, scaleX: 1, scaleY: 1 }) },
      elRect: { left: 0, top: 0 },
      opt: {
        outerFramePaddingX: 10,
        outerFramePaddingY: 10,
        defaultOuterFrameText: '外框',
      },
    },
  }

  renderOuterFrames.call(context)
  assert.equal(clearCount, 0)
  assert.equal(discardCount, 0)
  assert.equal(context.activeOuterFrame.el, frameElement)
  assert.equal(context.activeOuterFrame.textNode, textNode)
  assert.equal(context.activeOuterFrame.groupId, 'frame-1')
  assert.deepEqual(context.activeOuterFrame.memberUids, ['member-a', 'member-b'])
  assert.equal(positionUpdateCount, 1)
})

test('外框编辑身份不从远端更新后的旧 range 重算且成员重排仍可重绑', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/plugins/OuterFrame.js', import.meta.url),
    'utf8',
  )
  const captureMethod = extractMethod(
    source,
    'captureActiveOuterFrameTextEditForRender()',
    'matchesActiveOuterFrameTextEdit(snapshot, nodeList)',
  )
  const matchMethod = extractMethod(
    source,
    'matchesActiveOuterFrameTextEdit(snapshot, nodeList)',
    'restoreActiveOuterFrameTextEditAfterRender(',
  )
  const capture = Function(
    `'use strict'; return function (${captureMethod.args}) {${captureMethod.body}}`,
  )()
  const matches = Function(
    `'use strict'; return function (${matchMethod.args}) {${matchMethod.body}}`,
  )()

  const identity = {
    groupId: 'frame-1',
    memberUids: ['member-a', 'member-b'],
  }
  const captured = capture.call({
    showTextEdit: true,
    activeOuterFrame: {
      node: { children: ['unrelated', 'member-a', 'member-b'] },
      range: [0, 1],
      ...identity,
    },
    getRangeNodeList() {
      throw new Error('缓存身份存在时不得使用已经过期的 range')
    },
  })
  assert.deepEqual(captured, identity)
  assert.notStrictEqual(captured.memberUids, identity.memberUids)

  const reorderedMembers = [
    createRuntimeNode('member-b', {
      outerFrame: { groupId: 'frame-1' },
    }),
    createRuntimeNode('member-a', {
      outerFrame: { groupId: 'frame-1' },
    }),
  ]
  assert.equal(matches(captured, reorderedMembers), true)
  assert.equal(matches(captured, reorderedMembers.slice(0, 1)), false)
})
