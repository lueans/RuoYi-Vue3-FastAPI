import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { parseHTML } from 'linkedom'
import { renderRuntimeTreeSync } from '../../libs/simple-mind-map/src/utils/runtimeTree.js'
import { rebindRuntimeNodesToRenderTree } from '../../libs/simple-mind-map/src/utils/nodeData.js'

import {
  bufferPendingNodeTextEditInput,
  captureInsertedNodeRollbackState,
  isNodeTextEditOccupied,
  resolveCurrentNodeTextEditTarget,
  rollbackRejectedInsertedNode,
  reusePendingNodeTextEditAdmission,
  shouldBlockNodeTextEditByPresence,
} from '../../libs/simple-mind-map/src/core/render/node/nodeCooperateState.js'
import { getNodeEditLeaseBlockedMessage } from '../mindmap-node-edit-lease.js'

function extractTextEditMethod(source, signature) {
  const start = source.indexOf(`  ${signature} {`)
  assert.ok(start >= 0, `missing TextEdit method: ${signature}`)
  const openBrace = source.indexOf('{', start)
  let depth = 0
  let closeBrace = -1
  for (let index = openBrace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') {
      depth -= 1
      if (depth === 0) {
        closeBrace = index
        break
      }
    }
  }
  assert.ok(closeBrace > openBrace, `unterminated TextEdit method: ${signature}`)
  return {
    args: signature.slice(signature.indexOf('(') + 1, signature.lastIndexOf(')')),
    body: source.slice(openBrace + 1, closeBrace),
  }
}

function compileTextEditMethod(source, signature, dependencies = {}) {
  const { args, body } = extractTextEditMethod(source, signature)
  const names = Object.keys(dependencies)
  return Function(
    ...names,
    `'use strict'; return function (${args}) {${body}}`,
  )(...names.map(name => dependencies[name]))
}

test('普通单选和多选 Presence 不会构成节点文本编辑占用', () => {
  const node = {
    userList: [
      { id: 2, sessionId: 'browser-b' },
      { id: 3, sessionId: 'browser-c' },
    ],
    editingUserList: [],
  }

  assert.equal(isNodeTextEditOccupied(node), false)
})

test('实际编辑会话才构成占用且最后一个会话释放后立即恢复', () => {
  const node = {
    userList: [],
    editingUserList: [{ id: 2, sessionId: 'browser-b' }],
  }

  assert.equal(isNodeTextEditOccupied(node), true)
  node.editingUserList.splice(0, 1)
  assert.equal(isNodeTextEditOccupied(node), false)
})

test('权威租约模式不会让迟到的 Presence 绕过服务端仲裁', () => {
  const node = {
    editingUserList: [{ id: 2, sessionId: 'stale-browser' }],
  }

  assert.equal(shouldBlockNodeTextEditByPresence(node, {
    enabled: true,
    authoritative: false,
  }), true)
  assert.equal(shouldBlockNodeTextEditByPresence(node, {
    enabled: true,
    authoritative: true,
  }), false)
})

test('画布双击入口与键盘入口统一服从权威租约而非 Presence', async () => {
  const source = await readFile(
    new URL(
      '../../libs/simple-mind-map/src/core/render/node/MindMapNode.js',
      import.meta.url,
    ),
    'utf8',
  )
  const doubleClickBlock = source.match(
    /handleNodeDoubleClick\(e\) \{[\s\S]*?\n  \}/,
  )?.[0] || ''

  assert.match(doubleClickBlock, /isNodeTextEditLeaseAuthoritative/)
  assert.match(doubleClickBlock, /shouldBlockNodeTextEditByPresence/)
  assert.match(doubleClickBlock, /authoritative: isNodeTextEditLeaseAuthoritative\?\.\(\) === true/)
})

test('普通文本和富文本都先提交最终命令再释放节点租约', async () => {
  const [plainSource, richSource] = await Promise.all([
    readFile(
      new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
      'utf8',
    ),
    readFile(
      new URL('../../libs/simple-mind-map/src/plugins/RichText.js', import.meta.url),
      'utf8',
    ),
  ])
  for (const source of [plainSource, richSource]) {
    const hideBody = source.match(/hideEditText(?:Box)?\([^)]*\) \{([\s\S]*?)\n  \}/)?.[1] || ''
    const commitIndex = hideBody.indexOf("execCommand('SET_NODE_TEXT'")
    const flushIndex = hideBody.indexOf('flushPendingHistory?.()')
    const releaseIndex = hideBody.indexOf("emit('node_text_edit_end'")
    assert.ok(commitIndex >= 0)
    assert.ok(flushIndex > commitIndex)
    assert.ok(releaseIndex > flushIndex)
    assert.match(
      hideBody,
      /try \{[\s\S]*execCommand\('SET_NODE_TEXT'[\s\S]*flushPendingHistory\?\.\(\)[\s\S]*\} finally \{[\s\S]*emit\('node_text_edit_end'/,
    )
  }
})

test('公式插入先获权威租约且多节点串行提交后释放', async () => {
  const [formulaSource, renderSource] = await Promise.all([
    readFile(
      new URL('../../libs/simple-mind-map/src/plugins/Formula.js', import.meta.url),
      'utf8',
    ),
    readFile(
      new URL('../../libs/simple-mind-map/src/core/render/Render.js', import.meta.url),
      'utf8',
    ),
  ])
  const formulaStart = formulaSource.indexOf('async insertFormulaToNode(')
  const formulaEnd = formulaSource.indexOf('// 将公式富文本转换为公式源码', formulaStart)
  const formulaBody = formulaSource.slice(formulaStart, formulaEnd)
  const acquireIndex = formulaBody.indexOf('await beforeTextEdit(node, false)')
  const resolveIndex = formulaBody.indexOf('resolveCurrentNodeTextEditTarget(')
  const showIndex = formulaBody.indexOf('richTextPlugin.showEditText')
  const insertIndex = formulaBody.indexOf('richTextPlugin.quill.insertEmbed')
  const hideIndex = formulaBody.indexOf('richTextPlugin.hideEditText([targetNode])')
  const releaseIndex = formulaBody.lastIndexOf('releaseNodeTextEditLease?.(leasedNodeUid)')

  assert.ok(acquireIndex >= 0)
  assert.ok(resolveIndex > acquireIndex)
  assert.ok(showIndex > resolveIndex)
  assert.ok(insertIndex > showIndex)
  assert.ok(hideIndex > insertIndex)
  assert.ok(releaseIndex > hideIndex)
  assert.match(formulaBody, /if \([\s\S]*await beforeTextEdit\(node, false\) !== true[\s\S]*\) return false/)
  assert.match(formulaBody, /if \(!targetNode\) return false/)
  assert.match(formulaBody, /finally \{[\s\S]*releaseNodeTextEditLease\?\.\(leasedNodeUid\)/)

  const batchStart = formulaSource.indexOf('async insertFormulaToNodes(')
  const batchEnd = formulaSource.indexOf('// 将公式富文本转换为公式源码', batchStart)
  const batchBody = formulaSource.slice(batchStart, batchEnd)
  assert.match(batchBody, /if \(this\.mindMap\.opt\.readonly\) return 0/)
  assert.match(
    batchBody,
    /for \(const node of list\) \{[\s\S]*await this\.insertFormulaToNode\(node, formula\)[\s\S]*insertedCount \+= 1/,
  )
  assert.match(batchBody, /return insertedCount/)

  const renderStart = renderSource.indexOf('async insertFormula(')
  const renderEnd = renderSource.indexOf('//  添加节点概要', renderStart)
  const renderBody = renderSource.slice(renderStart, renderEnd)
  assert.match(
    renderBody,
    /return this\.mindMap\.formula\.insertFormulaToNodes\(list, formula\)/,
  )
})

test('异步租约返回后按 UID 重新解析节点并在节点已删除时归还租约', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const showStart = source.indexOf('async show({')
  const showEnd = source.indexOf('// 当openRealtimeRenderOnNodeTextEdit', showStart)
  const showBody = source.slice(showStart, showEnd)
  const awaitIndex = showBody.indexOf('await beforeTextEdit')
  const resolveIndex = showBody.indexOf('resolveCurrentNodeTextEditTarget(node, this.renderer')
  const releaseIndex = showBody.indexOf('releaseNodeTextEditLease?.(leasedNodeUid)')
  assert.ok(awaitIndex >= 0)
  assert.ok(resolveIndex > awaitIndex)
  assert.ok(releaseIndex > resolveIndex)
  assert.match(showBody, /readonly: this\.mindMap\.opt\.readonly/)
  assert.match(showBody, /node = currentNode/)

  const originalNode = { uid: 'child' }
  const replacementNode = { uid: 'child' }
  let currentNode = originalNode
  let resolveLease
  const leaseResult = new Promise(resolve => { resolveLease = resolve })
  const continueAfterLease = leaseResult.then(() => resolveCurrentNodeTextEditTarget(
    originalNode,
    { findNodeByUid: () => currentNode },
    { authoritative: true },
  ))
  currentNode = null
  resolveLease(true)
  assert.equal(await continueAfterLease, null)
  currentNode = replacementNode
  assert.equal(resolveCurrentNodeTextEditTarget(
    originalNode,
    { findNodeByUid: () => currentNode },
    { authoritative: true },
  ), replacementNode)
})

test('异步编辑准入在等待前冻结插入快照且取消时先补偿再释放', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const showStart = source.indexOf('async show({')
  const showEnd = source.indexOf('// 当openRealtimeRenderOnNodeTextEdit', showStart)
  const showBody = source.slice(showStart, showEnd)
  const captureIndex = showBody.indexOf('captureInsertedNodeRollbackState(node')
  const awaitIndex = showBody.indexOf('await beforeTextEdit(node, isInserting)')
  const admissionIdentityIndex = showBody.indexOf(
    'this.pendingTextEditAdmission !== admission',
  )
  assert.ok(captureIndex >= 0)
  assert.ok(awaitIndex > captureIndex)
  assert.ok(admissionIdentityIndex > awaitIndex)
  assert.match(
    showBody,
    /const insertionRollbackState[\s\S]*?finally \{[\s\S]*?rollbackRejectedInsertion\(insertionRollbackState\)/,
  )

  const cancelBody = source.match(
    /cancelPendingTextEditAdmission\(\) \{([\s\S]*?)\n  \}/,
  )?.[1] || ''
  const rollbackIndex = cancelBody.indexOf('rollbackRejectedInsertion')
  const releaseIndex = cancelBody.indexOf('releaseNodeTextEditLease')
  assert.ok(rollbackIndex >= 0)
  assert.ok(releaseIndex > rollbackIndex)
  assert.match(source, /hideEditTextBox\(\) \{\s*this\.cancelPendingTextEditAdmission\(\)/)
})

test('新节点租约等待期间的重复键盘入口复用准入并保留全部输入', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const showStart = source.indexOf('async show({')
  const showEnd = source.indexOf('// 当openRealtimeRenderOnNodeTextEdit', showStart)
  const showBody = source.slice(showStart, showEnd)
  const keydownBody = source.match(
    /onKeydown\(e\) \{([\s\S]*?)\n  \}/,
  )?.[1] || ''
  const bufferIndex = keydownBody.indexOf('bufferPendingNodeTextEditInput(')
  const bodyTargetIndex = keydownBody.indexOf('e.target !== document.body')
  const autoEnterIndex = keydownBody.indexOf('this.checkIsAutoEnterTextEditKey(e)')
  assert.ok(bufferIndex >= 0)
  assert.ok(bodyTargetIndex > bufferIndex)
  assert.ok(autoEnterIndex > bufferIndex)
  assert.match(
    keydownBody,
    /bufferPendingNodeTextEditInput\([\s\S]*?e\.preventDefault\(\)[\s\S]*?return/,
  )
  const reuseIndex = showBody.indexOf('reusePendingNodeTextEditAdmission(')
  const reuseCurrentIndex = showBody.indexOf('this.reuseCurrentTextEdit(')
  const cancelIndex = showBody.indexOf('this.cancelPendingTextEditAdmission()')
  const awaitIndex = showBody.indexOf('await beforeTextEdit(node, isInserting)')
  const replayIndex = showBody.indexOf('this.applyPendingTextEditInput(')
  assert.ok(reuseIndex >= 0)
  assert.ok(reuseCurrentIndex > reuseIndex)
  assert.ok(cancelIndex > reuseCurrentIndex)
  assert.ok(awaitIndex > cancelIndex)
  assert.ok(replayIndex > awaitIndex)
  assert.match(
    showBody,
    /if \(reusePendingNodeTextEditAdmission\([\s\S]*?\)\) return/,
  )

  const pendingAdmission = {
    nodeUid: 'new-node',
    rollbackState: { nodeUid: 'new-node' },
    pendingInputText: '',
    pendingInputTouched: false,
  }
  const node = { getData: key => key === 'uid' ? 'new-node' : undefined }
  for (const key of ['1', '1', '1', '2']) {
    assert.equal(bufferPendingNodeTextEditInput(
      pendingAdmission,
      node,
      { key },
    ), true)
  }
  assert.equal(bufferPendingNodeTextEditInput(
    pendingAdmission,
    node,
    { key: 'Backspace', keyCode: 8 },
  ), true)
  assert.equal(bufferPendingNodeTextEditInput(
    pendingAdmission,
    node,
    { key: '1' },
  ), true)
  assert.equal(bufferPendingNodeTextEditInput(
    pendingAdmission,
    node,
    { key: 'Delete', keyCode: 46 },
  ), true)
  for (const key of ['-', 'a', ' ', '中']) {
    assert.equal(bufferPendingNodeTextEditInput(
      pendingAdmission,
      node,
      { key },
    ), true)
  }
  assert.equal(pendingAdmission.pendingInputText, '1111-a 中')
  assert.equal(pendingAdmission.pendingInputTouched, true)
  assert.equal(reusePendingNodeTextEditAdmission(
    pendingAdmission,
    node,
    { type: 'dblclick' },
  ), true)
  assert.equal(
    reusePendingNodeTextEditAdmission(
      pendingAdmission,
      { getData: () => 'other-node' },
      { key: '2', keyCode: 50 },
    ),
    false,
  )
  assert.equal(pendingAdmission.pendingInputText, '1111-a 中')
  assert.match(
    source,
    /window\.addEventListener\('keydown', this\.onKeydown, true\)/,
  )
  assert.doesNotMatch(
    source,
    /opt\.enableAutoEnterTextEditWhenKeydown\s*\?\s*'addEventListener'/,
  )
  assert.match(showBody, /this\.createPendingTextEditInput\(admission, node, isInserting\)/)
  assert.match(source, /input\.addEventListener\('compositionstart'/)
  assert.match(source, /input\.addEventListener\('compositionend'/)
  assert.match(source, /if \(opened && pendingInputTouched\)/)
})

test('画布容器持有焦点时仍能由键盘进入节点编辑', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const document = { body: {} }
  const onKeydown = compileTextEditMethod(
    source,
    'onKeydown(e)',
    {
      document,
      bufferPendingNodeTextEditInput: () => false,
    },
  )
  const canvas = {}
  const node = { getData: key => key === 'uid' ? 'selected' : undefined }
  let shown = null
  let prevented = false
  onKeydown.call({
    pendingTextEditAdmission: null,
    mindMap: {
      el: canvas,
      renderer: { activeNodeList: [node] },
      opt: { enableAutoEnterTextEditWhenKeydown: true },
    },
    isEditableTextInputTarget: () => false,
    queuePendingTextEditContinuation: () => false,
    isShowTextEdit: () => false,
    checkIsAutoEnterTextEditKey: () => true,
    show: params => { shown = params },
  }, {
    target: canvas,
    key: '1',
    keyCode: 49,
    preventDefault: () => { prevented = true },
  })

  assert.equal(prevented, true)
  assert.equal(shown?.node, node)
  assert.equal(shown?.isFromKeyDown, true)

  const pendingAdmission = {
    nodeUid: 'pending-node',
    pendingInputText: '',
    pendingInputTouched: false,
  }
  let pendingPrevented = false
  const pendingOnKeydown = compileTextEditMethod(
    source,
    'onKeydown(e)',
    { document, bufferPendingNodeTextEditInput },
  )
  pendingOnKeydown.call({
    pendingTextEditAdmission: pendingAdmission,
    renderer: { findNodeByUid: () => null },
    mindMap: {
      el: canvas,
      renderer: { activeNodeList: [] },
      opt: { enableAutoEnterTextEditWhenKeydown: true },
    },
    isEditableTextInputTarget: () => false,
    queuePendingTextEditContinuation: () => false,
  }, {
    target: document.body,
    key: '1',
    keyCode: 49,
    preventDefault: () => { pendingPrevented = true },
  })
  assert.equal(pendingPrevented, true)
  assert.equal(pendingAdmission.pendingInputText, '1')

  // 概要数组重排时旧 runtime 可能已从 summary-a 复用成 summary-b。
  // 键盘入口仍必须把冻结 UID 交给 same-editor reuse，不能关闭后在 B 上重开。
  const reuseCurrent = compileTextEditMethod(
    source,
    'reuseCurrentTextEdit(node, event, isFromKeyDown = false)',
  )
  const reusedSummaryRuntime = { getData: () => 'summary-b' }
  let frozenTargetUid = ''
  let summaryInput = ''
  let summaryFocusCount = 0
  const summaryContext = {
    currentNode: reusedSummaryRuntime,
    currentTextEditNodeUid: 'summary-a',
    pendingTextEditAdmission: null,
    textEditNode: { focus: () => { summaryFocusCount += 1 } },
    renderer: { findNodeByUid: () => null },
    mindMap: {
      el: canvas,
      richText: null,
      renderer: { activeNodeList: [] },
      opt: { enableAutoEnterTextEditWhenKeydown: true },
    },
    isEditableTextInputTarget: () => false,
    queuePendingTextEditContinuation: () => false,
    isShowTextEdit: () => true,
    getCurrentEditNode: () => reusedSummaryRuntime,
    checkIsAutoEnterTextEditKey: () => true,
    updateTextEditNode: () => assert.fail('runtime 空窗不应重绑概要旧实例'),
    applyPendingTextEditInput: text => { summaryInput += text },
  }
  summaryContext.show = ({ node: target, e, isFromKeyDown }) => {
    frozenTargetUid = target.uid || target.getData?.('uid') || ''
    assert.equal(reuseCurrent.call(
      summaryContext,
      target,
      e,
      isFromKeyDown,
    ), true)
  }
  onKeydown.call(summaryContext, {
    target: canvas,
    key: '3',
    keyCode: 51,
    preventDefault: () => {},
  })
  assert.equal(frozenTargetUid, 'summary-a')
  assert.equal(summaryInput, '3')
  assert.equal(summaryFocusCount, 1)
  assert.equal(summaryContext.currentTextEditNodeUid, 'summary-a')
})

test('已打开的同一节点编辑器复用现有 DOM 并保留后续按键', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const reuseCurrent = compileTextEditMethod(
    source,
    'reuseCurrentTextEdit(node, event, isFromKeyDown = false)',
  )
  const oldNode = { getData: () => 'new-node' }
  const currentNode = { getData: () => 'new-node' }
  let appliedText = ''
  let updates = 0
  let focusCount = 0
  const richOrder = []
  const richText = {
    node: oldNode,
    quill: { focus: () => { focusCount += 1; richOrder.push('focus') } },
  }
  const context = {
    currentTextEditNodeUid: 'new-node',
    mindMap: { richText },
    renderer: { findNodeByUid: () => currentNode },
    isShowTextEdit: () => true,
    getCurrentEditNode: () => richText.node,
    updateTextEditNode: () => { updates += 1 },
    applyPendingTextEditInput: text => {
      richOrder.push('input')
      appliedText += text
    },
  }

  assert.equal(reuseCurrent.call(
    context,
    currentNode,
    { key: '1' },
    true,
  ), true)
  assert.strictEqual(richText.node, currentNode)
  assert.equal(appliedText, '1')
  assert.equal(updates, 1)
  assert.equal(focusCount, 1)
  assert.deepEqual(richOrder, ['focus', 'input'])
  assert.equal(reuseCurrent.call(
    context,
    { getData: () => 'other-node' },
    { type: 'dblclick' },
    false,
  ), false)

  const plainNode = { getData: () => 'plain-node' }
  let plainFocusCount = 0
  let plainInput = ''
  const plainOrder = []
  const plainContext = {
    currentNode: plainNode,
    currentTextEditNodeUid: 'plain-node',
    textEditNode: {
      focus: () => { plainFocusCount += 1; plainOrder.push('focus') },
    },
    mindMap: { richText: null },
    // 模拟 Render._render 暂时清空 runtime root 的窗口；已有编辑器仍须
    // 接住按键，不能返回 show() 的关闭重开路径。
    renderer: { findNodeByUid: () => null },
    isShowTextEdit: () => true,
    getCurrentEditNode: () => plainNode,
    updateTextEditNode: () => assert.fail('换树窗口不应读取旧 SVG 几何'),
    applyPendingTextEditInput: text => {
      plainOrder.push('input')
      plainInput += text
    },
  }
  assert.equal(reuseCurrent.call(
    plainContext,
    plainNode,
    { key: '2' },
    true,
  ), true)
  assert.equal(plainInput, '2')
  assert.equal(plainFocusCount, 1)
  assert.deepEqual(plainOrder, ['focus', 'input'])

  const showEditStart = source.indexOf('  showEditTextBox({')
  const showEditEnd = source.indexOf('  // 派发节点文本编辑事件', showEditStart)
  const showEditBody = source.slice(showEditStart, showEditEnd)
  const explicitFocusIndex = showEditBody.indexOf('this.textEditNode.focus?.(')
  const selectionIndex = showEditBody.indexOf('if (isInserting ||')
  assert.ok(explicitFocusIndex >= 0)
  assert.ok(selectionIndex > explicitFocusIndex)
})

test('待准入输入使用原生编辑控件保留 IME、分段命令和取消语义', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const { document, window } = parseHTML('<html><body></body></html>')
  const queueContinuation = compileTextEditMethod(
    source,
    'queuePendingTextEditContinuation(admission, node, event)',
  )
  const createInput = compileTextEditMethod(
    source,
    'createPendingTextEditInput(admission, node, isInserting)',
    {
      document,
      getTextFromHtml: value => value.replace(/<[^>]+>/g, ''),
      SMM_NODE_EDIT_WRAP: 'smm-node-edit-wrap',
    },
  )
  const waitForComposition = compileTextEditMethod(
    source,
    'waitForPendingTextEditComposition(admission)',
  )
  const removeInput = compileTextEditMethod(
    source,
    'removePendingTextEditInput(admission)',
  )
  const snapshotInput = compileTextEditMethod(
    source,
    'snapshotPendingTextEditInput(admission)',
  )
  const admission = { nodeUid: 'new-node' }
  const node = {
    getData(key) {
      return { uid: 'new-node', text: '分支主题', richText: false }[key]
    },
  }
  const context = {
    pendingTextEditAdmission: admission,
    mindMap: { opt: { customInnerElsAppendTo: null } },
    queuePendingTextEditContinuation: queueContinuation,
  }
  createInput.call(context, admission, node, true)
  const input = admission.pendingInputElement
  assert.ok(input)
  assert.equal(input.value, '分支主题')

  input.dispatchEvent(new window.Event('compositionstart'))
  input.value = 'ni'
  input.dispatchEvent(new window.Event('input'))
  let compositionSettled = false
  const composition = waitForComposition.call(context, admission).then(value => {
    compositionSettled = true
    return value
  })
  await Promise.resolve()
  assert.equal(compositionSettled, false, '服务端 grant 不得中断正在选择的中文候选')
  input.value = '你'
  input.dispatchEvent(new window.Event('compositionend'))
  assert.equal(await composition, true)

  const enter = new window.Event('keydown', { bubbles: true, cancelable: true })
  Object.defineProperties(enter, {
    key: { value: 'Enter' },
    keyCode: { value: 13 },
    isComposing: { value: false },
  })
  input.dispatchEvent(enter)
  input.value = '好'
  input.dispatchEvent(new window.Event('input'))
  assert.deepEqual(admission.pendingInputSegments, [
    { text: '你', touched: true, continuationCommand: 'INSERT_NODE' },
    { text: '好', touched: true, continuationCommand: '' },
  ])

  input.value = '好1111'
  admission.pendingInputNativeActivity = true
  assert.equal(snapshotInput.call(context, admission), true)
  assert.strictEqual(context.pendingTextEditAdmission, admission)
  assert.equal(input.isConnected, true)
  assert.equal(admission.pendingInputText, '好1111')
  assert.equal(admission.pendingInputSegments[1].text, '好1111')

  input.dispatchEvent(new window.Event('compositionstart'))
  const cancelledComposition = waitForComposition.call(context, admission)
  removeInput.call(context, admission)
  assert.equal(await cancelledComposition, false)
  assert.equal(input.isConnected, false)
})

test('连续录入分段跨 RAF 精确移交且后续输入只追加到最后一段', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const finish = compileTextEditMethod(
    source,
    'finishTextEditAndInsert(command)',
  )
  const continueSequence = compileTextEditMethod(
    source,
    'continuePendingTextEditSequence(nodeUid, command, remainingSegments)',
  )
  const takeDeferred = compileTextEditMethod(
    source,
    'takeDeferredPendingTextEditSegments(node, isInserting)',
  )
  const installSegments = compileTextEditMethod(
    source,
    'installPendingTextEditSegments(admission, segments)',
  )
  const currentData = { data: { uid: 'current' }, children: [] }
  const parentData = { data: { uid: 'parent' }, children: [currentData] }
  const currentNode = {
    parent: { nodeData: parentData },
    nodeData: currentData,
    getData: key => key === 'uid' ? 'current' : undefined,
  }
  const context = {
    deferredPendingTextEditSequence: null,
    pendingTextEditAdmission: null,
    getCurrentEditNode: () => currentNode,
    hideEditTextBox() {},
    finishTextEditAndInsert: finish,
    mindMap: {
      execCommand(command) {
        assert.equal(command, 'INSERT_NODE')
        // 真实 Render 在这里仅修改 renderTree，运行时节点/准入要到 RAF。
        parentData.children.push({ data: { uid: 'next-node' }, children: [] })
      },
    },
  }
  const queued = [
    { text: 'B', touched: true, continuationCommand: 'INSERT_NODE' },
    { text: 'C', touched: true, continuationCommand: '' },
  ]
  assert.equal(continueSequence.call(
    context,
    'current',
    'INSERT_NODE',
    queued,
  ), true)
  assert.equal(context.pendingTextEditAdmission, null)
  assert.equal(context.deferredPendingTextEditSequence.nodeUid, 'next-node')

  const nextNode = { getData: () => 'next-node' }
  const inherited = takeDeferred.call(context, nextNode, true)
  assert.deepEqual(inherited, queued)
  assert.equal(context.deferredPendingTextEditSequence, null)

  const admission = {
    nodeUid: 'next-node',
    pendingInputElement: {
      value: '',
      setSelectionRange(start, end) { this.selection = [start, end] },
    },
  }
  installSegments.call(context, admission, inherited)
  assert.equal(admission.pendingInputSegmentIndex, 1)
  assert.equal(admission.pendingInputElement.value, 'C')
  bufferPendingNodeTextEditInput(admission, nextNode, { key: 'D' })
  assert.equal(admission.pendingInputSegments[0].text, 'B')
  assert.equal(admission.pendingInputSegments[1].text, 'CD')

  const scheduleCleanup = compileTextEditMethod(
    source,
    'scheduleDeferredPendingTextEditSequenceCleanup()',
    { queueMicrotask },
  )
  const renderOrderContext = {
    deferredPendingTextEditSequence: {
      nodeUid: 'rendered-node',
      segments: queued,
    },
    pendingTextEditAdmission: null,
  }
  let renderOrderSegments = []
  renderRuntimeTreeSync(
    { uid: 'rendered-node', children: [] },
    () => {},
    renderedNode => {
      renderOrderSegments = takeDeferred.call(
        renderOrderContext,
        renderedNode,
        true,
      )
    },
    () => scheduleCleanup.call(renderOrderContext),
  )
  assert.deepEqual(renderOrderSegments, queued)
  assert.equal(renderOrderContext.deferredPendingTextEditSequence, null)
  await Promise.resolve()
  assert.deepEqual(renderOrderSegments, queued)
})

test('概要运行时重建后普通与富文本编辑器都按持久 UID 换绑', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const rebind = compileTextEditMethod(
    source,
    'rebindCurrentTextEditNodeAfterRender()',
  )
  let oldSummaryPersistentUid = 'summary'
  const oldSummary = {
    uid: 'runtime-old',
    getData: () => oldSummaryPersistentUid,
  }
  const newSummary = { uid: 'runtime-new', getData: () => 'summary' }

  const plain = {
    currentNode: oldSummary,
    currentTextEditNodeUid: 'summary',
    getCurrentEditNode() { return this.currentNode },
    renderer: { findNodeByUid: uid => uid === 'summary' ? newSummary : null },
    mindMap: { richText: null },
  }
  // 模拟概要等长重排：旧 runtime 已被下标复用成另一概要，只有编辑开始时
  // 冻结的持久 UID 仍能找到真正正在编辑的新 runtime。
  oldSummaryPersistentUid = 'other-summary'
  assert.equal(rebind.call(plain), true)
  assert.strictEqual(plain.currentNode, newSummary)

  const richText = { node: oldSummary }
  const rich = {
    currentTextEditNodeUid: 'summary',
    getCurrentEditNode: () => richText.node,
    renderer: { findNodeByUid: uid => uid === 'summary' ? newSummary : null },
    mindMap: { richText },
  }
  assert.equal(rebind.call(rich), true)
  assert.strictEqual(richText.node, newSummary)
  assert.match(
    source,
    /editingUid === activeUid/,
    '同一概要的新 runtime 激活不能在 render_end 换绑前关闭编辑器',
  )
})

test('updateData 到 RAF 之间旧 runtime 立即换绑当前 renderTree', () => {
  const oldChildData = {
    data: {
      uid: 'child',
      text: '旧标题',
      associativeLineText: { target: '旧关联文字' },
      outerFrame: { groupId: 'group', text: '旧外框文字' },
    },
    children: [],
  }
  const oldRootData = {
    data: {
      uid: 'root',
      generalization: [{ uid: 'summary', text: '旧概要' }],
    },
    children: [oldChildData],
  }
  const runtimeNode = (uid, nodeData) => ({
    uid: `runtime-${uid}`,
    nodeData,
    children: [],
    getData(key) { return this.nodeData.data[key] },
  })
  const rootRuntime = runtimeNode('root', oldRootData)
  const childRuntime = runtimeNode('child', oldChildData)
  rootRuntime.children = [childRuntime]
  childRuntime.parent = rootRuntime
  const summaryRuntime = {
    ...runtimeNode('summary', {
      data: oldRootData.data.generalization[0],
      children: [],
    }),
    isGeneralization: true,
    generalizationBelongNode: rootRuntime,
  }
  rootRuntime._generalizationList = [{ generalizationNode: summaryRuntime }]

  const currentTree = structuredClone(oldRootData)
  currentTree.children.push({
    data: { uid: 'remote-only', text: '远端新增' },
    children: [],
  })
  assert.equal(
    rebindRuntimeNodesToRenderTree(rootRuntime, currentTree),
    3,
  )
  assert.strictEqual(rootRuntime.nodeData, currentTree)
  assert.strictEqual(childRuntime.nodeData, currentTree.children[0])
  assert.strictEqual(
    summaryRuntime.nodeData.data,
    currentTree.data.generalization[0],
  )
  assert.strictEqual(currentTree._node, rootRuntime)
  assert.strictEqual(currentTree.children[0]._node, childRuntime)

  // 模拟普通/大纲、关联线、外框和概要编辑器在 render_end 前提交。
  childRuntime.nodeData.data.text = '最后输入'
  childRuntime.nodeData.data.associativeLineText.target = '新关联文字'
  childRuntime.nodeData.data.outerFrame.text = '新外框文字'
  summaryRuntime.nodeData.data.text = '新概要'
  assert.equal(currentTree.children[0].data.text, '最后输入')
  assert.equal(
    currentTree.children[0].data.associativeLineText.target,
    '新关联文字',
  )
  assert.equal(currentTree.children[0].data.outerFrame.text, '新外框文字')
  assert.equal(currentTree.data.generalization[0].text, '新概要')
})

test('runtime 换绑优先当前 root 而不是同 UID 的已销毁旧缓存', () => {
  const currentData = {
    data: { uid: 'same', text: '当前实例' },
    children: [],
  }
  const staleData = {
    data: { uid: 'same', text: '旧缓存' },
    children: [],
  }
  const createRuntime = nodeData => ({
    uid: 'runtime',
    nodeData,
    children: [],
    getData(key) { return this.nodeData.data[key] },
  })
  const currentRuntime = createRuntime(currentData)
  const staleRuntime = createRuntime(staleData)
  const nextTree = {
    data: { uid: 'same', text: '远端版本' },
    children: [],
  }

  assert.equal(
    rebindRuntimeNodesToRenderTree(
      [currentRuntime, currentRuntime, staleRuntime],
      nextTree,
    ),
    1,
  )
  assert.strictEqual(currentRuntime.nodeData, nextTree)
  assert.strictEqual(staleRuntime.nodeData, staleData)
  assert.strictEqual(nextTree._node, currentRuntime)
})

test('缩放只重定位现有编辑器且不会重新申请租约或转存输入', async () => {
  const [source, richSource] = await Promise.all([
    readFile(
      new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
      'utf8',
    ),
    readFile(
      new URL('../../libs/simple-mind-map/src/plugins/RichText.js', import.meta.url),
      'utf8',
    ),
  ])
  const onScale = compileTextEditMethod(source, 'onScale()')
  let updates = 0
  const node = { uid: 'editing' }
  const context = {
    getCurrentEditNode: () => node,
    updateTextEditNode: () => { updates += 1 },
  }
  onScale.call(context)
  assert.equal(updates, 1)
  const onScaleBody = extractTextEditMethod(source, 'onScale()').body
  assert.doesNotMatch(onScaleBody, /this\.show\(/)
  assert.doesNotMatch(onScaleBody, /cacheEditingText/)
  assert.doesNotMatch(onScaleBody, /showTextEdit\s*=\s*false/)
  const richUpdateBody = richSource.match(
    /updateTextEditNode\(\) \{([\s\S]*?)\n  \}/,
  )?.[1] || ''
  assert.match(richUpdateBody, /style\.transform = `scale\(/)
  assert.match(richUpdateBody, /addNodeTextStyleToTextEditNode/)
  assert.match(richUpdateBody, /this\.node\.hasCustomWidth\(\)/)

  const updateRichTextEditNode = compileTextEditMethod(
    richSource,
    'updateTextEditNode()',
  )
  const textEditNode = { style: {} }
  const richNode = {
    customTextWidth: 360,
    hasCustomWidth: () => true,
    _textData: {
      node: {
        node: {
          getBoundingClientRect: () => ({
            width: 240,
            height: 80,
            left: 16,
            top: 24,
          }),
        },
        attr: name => (name === 'data-width' ? 120 : 40),
      },
    },
  }
  updateRichTextEditNode.call({
    node: richNode,
    mindMap: { opt: { textAutoWrapWidth: 200 } },
    textNodePaddingX: 8,
    textNodePaddingY: 4,
    textEditNode,
    addNodeTextStyleToTextEditNode() {},
    setQuillContainerMinHeight() {},
  })
  assert.equal(textEditNode.style.maxWidth, '376px')
  assert.equal(textEditNode.style.transform, 'scale(2, 2)')
})

test('隐藏输入框聚焦失败时 fallback 分段不会被 textarea 旧值覆盖', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const queueContinuation = compileTextEditMethod(
    source,
    'queuePendingTextEditContinuation(admission, node, event)',
  )
  const input = {
    value: '分支主题',
    ownerDocument: { activeElement: null },
    setSelectionRange() {},
  }
  const admission = {
    nodeUid: 'new-node',
    pendingInputElement: input,
    pendingInputText: '',
    pendingInputTouched: false,
    pendingInputSegments: [{
      text: '分支主题',
      touched: false,
      continuationCommand: '',
    }],
    pendingInputSegmentIndex: 0,
  }
  const node = { getData: () => 'new-node' }

  bufferPendingNodeTextEditInput(admission, node, { key: 'a' })
  bufferPendingNodeTextEditInput(admission, node, { key: 'b' })
  assert.equal(queueContinuation.call({}, admission, node, {
    key: 'Enter',
    keyCode: 13,
    target: {},
  }), true)
  assert.deepEqual(admission.pendingInputSegments, [
    { text: 'ab', touched: true, continuationCommand: 'INSERT_NODE' },
    { text: '', touched: false, continuationCommand: '' },
  ])
})

test('待准入按键监听注册为捕获阶段并对称解绑', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  assert.match(
    source,
    /window\.addEventListener\('keydown', this\.onKeydown, true\)/,
  )
  assert.match(
    source,
    /window\.removeEventListener\('keydown', this\.onKeydown, true\)/,
  )
})

test('远端无关结构更新渲染后会重定位仍打开的普通和富文本编辑器', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const renderEndBody = source.match(
    /this\.mindMap\.on\('node_tree_render_end', \(\) => \{([\s\S]*?)\n    \}\)/,
  )?.[1] || ''
  assert.match(renderEndBody, /if \(!this\.isShowTextEdit\(\)\) return/)
  assert.match(renderEndBody, /if \(!this\.rebindCurrentTextEditNodeAfterRender\(\)\) return/)
  assert.match(renderEndBody, /this\.updateTextEditNode\(\)/)
  assert.doesNotMatch(renderEndBody, /isNeedUpdateTextEditNode/)

  const onRenderEnd = Function(
    `'use strict'; return function () { ${renderEndBody} }`,
  )()
  for (const editorKind of ['plain', 'rich']) {
    let positionUpdateCount = 0
    onRenderEnd.call({
      scheduleDeferredPendingTextEditSequenceCleanup() {},
      isShowTextEdit: () => true,
      rebindCurrentTextEditNodeAfterRender: () => true,
      updateTextEditNode: () => {
        positionUpdateCount += 1
      },
      editorKind,
    })
    assert.equal(positionUpdateCount, 1)
  }
  let hiddenUpdateCount = 0
  onRenderEnd.call({
    scheduleDeferredPendingTextEditSequenceCleanup() {},
    isShowTextEdit: () => false,
    rebindCurrentTextEditNodeAfterRender: () => true,
    updateTextEditNode: () => {
      hiddenUpdateCount += 1
    },
  })
  assert.equal(hiddenUpdateCount, 0)
})

test('获锁后打开编辑器失败会捕获异常并在未打开时归还租约', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/TextEdit.js', import.meta.url),
    'utf8',
  )
  const showStart = source.indexOf('async show({')
  const showEnd = source.indexOf('// 当openRealtimeRenderOnNodeTextEdit', showStart)
  const showBody = source.slice(showStart, showEnd)

  assert.match(showBody, /let opened = false/)
  assert.match(showBody, /catch \(error\)[\s\S]*errorHandler\(ERROR_TYPES\.BEFORE_TEXT_EDIT_ERROR, error\)/)
  assert.match(showBody, /finally \{[\s\S]*leasedNodeUid && !opened[\s\S]*releaseNodeTextEditLease\?\.\(leasedNodeUid\)/)
  assert.match(showBody, /if \(!opened\) \{[\s\S]*rollbackRejectedInsertion\(insertionRollbackState\)/)
  assert.doesNotMatch(showBody, /rollbackRejectedInsertion\(node, isInserting, insertionType\)/)
  assert.match(showBody, /this\.mindMap\.richText\.showEditText\(params\)[\s\S]*this\.isShowTextEdit\(\)/)
})

test('新节点编辑租约被拒绝时按持久化语义撤回并同步提交补偿', () => {
  const nodeData = {
    data: {
      uid: 'new-node',
      text: '节点内容',
      isActive: true,
      tag: [{ tagId: 'tag-1', categoryId: 'group-1', name: '本地展示名' }],
    },
    children: [],
  }
  const parentData = { data: { uid: 'parent' }, children: [nodeData] }
  const node = {
    uid: 'new-node',
    nodeData,
    parent: { nodeData: parentData },
    getData: key => nodeData.data[key],
  }
  // 真实布局器会写入这个 enumerable 回指；快照必须明确忽略它。
  nodeData._node = node
  // 远端整树回放可能改变键顺序、重建托管标签展示字段，并按本地选区
  // 恢复 isActive；这些都不属于临时节点的持久化正文变化。
  const replacementData = {
    data: {
      tag: [{ categoryId: 'group-1', tagId: 'tag-1', color: '#f00' }],
      isActive: false,
      text: '节点内容',
      uid: 'new-node',
    },
    children: [],
  }
  const replacementParentData = {
    data: { uid: 'parent' },
    children: [replacementData],
  }
  const replacementNode = {
    ...node,
    nodeData: replacementData,
    parent: { nodeData: replacementParentData },
    getData: key => replacementData.data[key],
  }
  replacementData._node = replacementNode
  const calls = []
  let currentNode = node
  const renderer = {
    findNodeByUid: () => currentNode,
    removeNode: nodes => calls.push(['remove', nodes]),
  }
  const mindMap = {
    command: {
      addHistory: () => calls.push(['history']),
      flushPendingHistory: () => calls.push(['flush']),
    },
    emit: (...args) => calls.push(['emit', ...args]),
  }
  const rollbackState = captureInsertedNodeRollbackState(node, {
    isInserting: true,
  })
  assert.ok(rollbackState)

  assert.equal(rollbackRejectedInsertedNode(
    rollbackState,
    renderer,
    mindMap,
  ), true)
  assert.deepEqual(calls.map(item => item[0]), ['remove', 'history', 'flush', 'emit'])
  assert.deepEqual(calls[0][1], [node])

  calls.length = 0
  currentNode = replacementNode
  assert.equal(rollbackRejectedInsertedNode(
    rollbackState,
    renderer,
    mindMap,
  ), true)
  assert.deepEqual(calls.map(item => item[0]), ['remove', 'history', 'flush', 'emit'])
  assert.deepEqual(calls[0][1], [replacementNode])
})

test('渲染器 root 置空期间取消准入仍从 renderTree 精确撤回默认节点', () => {
  const insertedData = {
    data: { uid: 'pending-node', text: '分支主题', isActive: true },
    children: [],
  }
  const siblingData = { data: { uid: 'existing' }, children: [] }
  const parentData = {
    data: { uid: 'parent' },
    children: [siblingData, insertedData],
  }
  const parentNode = {
    nodeData: parentData,
    getData: key => parentData.data[key],
  }
  const insertedNode = {
    nodeData: insertedData,
    parent: parentNode,
    getData: key => insertedData.data[key],
  }
  const state = captureInsertedNodeRollbackState(insertedNode, {
    isInserting: true,
  })
  const calls = []
  const renderer = {
    root: null,
    renderTree: parentData,
    findNodeByUid: () => null,
  }
  const mindMap = {
    render(callback) {
      calls.push('render')
      callback?.()
    },
    command: {
      addHistory: () => calls.push('history'),
      flushPendingHistory: () => calls.push('flush'),
    },
    emit: () => calls.push('emit'),
  }

  assert.equal(rollbackRejectedInsertedNode(state, renderer, mindMap), true)
  assert.deepEqual(parentData.children, [siblingData])
  assert.equal(siblingData.data.isActive, true)
  assert.deepEqual(calls, ['render', 'history', 'flush', 'emit'])
})

test('renderTree 已换代但 runtime 尚未重建时从新树撤回而非修改旧实例', () => {
  const oldInsertedData = {
    data: { uid: 'pending-node', text: '分支主题' },
    children: [],
  }
  const oldParentData = {
    data: { uid: 'parent' },
    children: [oldInsertedData],
  }
  const oldParentNode = {
    nodeData: oldParentData,
    getData: key => oldParentData.data[key],
  }
  const oldRuntimeNode = {
    nodeData: oldInsertedData,
    parent: oldParentNode,
    getData: key => oldInsertedData.data[key],
  }
  const state = captureInsertedNodeRollbackState(oldRuntimeNode, {
    isInserting: true,
  })
  const currentInsertedData = structuredClone(oldInsertedData)
  const currentParentData = {
    data: { uid: 'parent' },
    children: [currentInsertedData],
  }
  const calls = []
  const renderer = {
    renderTree: currentParentData,
    findNodeByUid: () => oldRuntimeNode,
    removeNode: () => calls.push('removed-old-runtime'),
  }
  const mindMap = {
    render: () => calls.push('render'),
    command: {
      addHistory: () => calls.push('history'),
      flushPendingHistory: () => calls.push('flush'),
    },
    emit: () => calls.push('emit'),
  }

  assert.equal(rollbackRejectedInsertedNode(state, renderer, mindMap), true)
  assert.deepEqual(currentParentData.children, [])
  assert.equal(currentParentData.data.isActive, true)
  assert.deepEqual(oldParentData.children, [oldInsertedData])
  assert.deepEqual(calls, ['render', 'history', 'flush', 'emit'])
})

test('回滚按父 UID 和原有兄弟相对顺序判断，允许无关兄弟增删但拒绝真实移动', () => {
  const beforeData = { data: { uid: 'before' }, children: [] }
  const insertedData = {
    data: { uid: 'new-node', text: '节点内容' },
    children: [],
  }
  const afterData = { data: { uid: 'after' }, children: [] }
  const parentData = {
    data: { uid: 'parent' },
    children: [beforeData, insertedData, afterData],
  }
  const parent = {
    nodeData: parentData,
    getData: key => parentData.data[key],
  }
  const insertedNode = {
    nodeData: insertedData,
    parent,
    getData: key => insertedData.data[key],
  }
  const removed = []
  const renderer = {
    findNodeByUid: () => insertedNode,
    removeNode: nodes => removed.push(nodes),
  }
  const mindMap = {
    command: { addHistory() {}, flushPendingHistory() {} },
    emit() {},
  }
  const state = captureInsertedNodeRollbackState(insertedNode, {
    isInserting: true,
  })
  assert.ok(state)

  // 协作者在目标前插入、并删除另一个无关兄弟，不会让默认节点失去补偿。
  parentData.children.splice(1, 0, {
    data: { uid: 'remote-before' },
    children: [],
  })
  parentData.children.splice(parentData.children.indexOf(afterData), 1)
  assert.equal(rollbackRejectedInsertedNode(state, renderer, mindMap), true)
  assert.deepEqual(removed, [[insertedNode]])

  // 若临时节点确实越过仍存在的原兄弟，说明发生了语义移动，必须保留。
  parentData.children = [insertedData, beforeData]
  removed.length = 0
  assert.equal(rollbackRejectedInsertedNode(state, renderer, mindMap), false)
  assert.deepEqual(removed, [])
})

test('回滚快照发现同实例数据、父关系或子节点变化时保留协作者状态', () => {
  const createFixture = () => {
    const nodeData = {
      data: { uid: 'new-node', text: '节点内容' },
      children: [],
    }
    const parentData = { data: { uid: 'parent' }, children: [nodeData] }
    const node = {
      uid: 'new-node',
      nodeData,
      parent: { nodeData: parentData },
      getData: key => node.nodeData.data[key],
    }
    nodeData._node = node
    return { node, nodeData, parentData }
  }
  const mindMap = { command: {}, emit() {} }

  {
    const { node, nodeData } = createFixture()
    const state = captureInsertedNodeRollbackState(node, { isInserting: true })
    nodeData.data.text = '协作者已修改'
    assert.equal(rollbackRejectedInsertedNode(
      state,
      { findNodeByUid: () => node, removeNode: () => assert.fail() },
      mindMap,
    ), false)
  }
  {
    const { node, nodeData } = createFixture()
    const state = captureInsertedNodeRollbackState(node, { isInserting: true })
    node.nodeData = { data: { ...nodeData.data }, children: [] }
    assert.equal(rollbackRejectedInsertedNode(
      state,
      { findNodeByUid: () => node, removeNode: () => assert.fail() },
      mindMap,
    ), false)
  }
  {
    const { node } = createFixture()
    const state = captureInsertedNodeRollbackState(node, { isInserting: true })
    node.nodeData.children.push({ data: { uid: 'remote-child' }, children: [] })
    assert.equal(rollbackRejectedInsertedNode(
      state,
      { findNodeByUid: () => node, removeNode: () => assert.fail() },
      mindMap,
    ), false)
  }
  {
    const { node } = createFixture()
    const state = captureInsertedNodeRollbackState(node, { isInserting: true })
    node.parent = { nodeData: { children: [node.nodeData] } }
    assert.equal(rollbackRejectedInsertedNode(
      state,
      { findNodeByUid: () => node, removeNode: () => assert.fail() },
      mindMap,
    ), false)
  }
})

test('新增父节点编辑租约被拒绝时解包原子树而不是删除它', () => {
  const childData = { data: { uid: 'existing-child' }, children: [] }
  const insertedData = {
    data: { uid: 'new-parent' },
    children: [childData],
  }
  const parentData = {
    data: { uid: 'parent' },
    children: [insertedData],
  }
  const insertedNode = {
    uid: 'new-parent',
    nodeData: insertedData,
    parent: { nodeData: parentData },
    getData: key => insertedData.data[key],
  }
  insertedData._node = insertedNode
  let promotedActivated = false
  const promotedNode = { active: () => { promotedActivated = true } }
  const calls = []
  const renderer = {
    findNodeByUid: uid => (
      uid === 'new-parent' ? insertedNode : promotedNode
    ),
    removeNodeFromActiveList: node => calls.push(['deactivate', node]),
    removeNode: () => calls.push(['unexpected-remove']),
  }
  const mindMap = {
    render: callback => {
      calls.push(['render'])
      callback()
    },
    command: {
      addHistory: () => calls.push(['history']),
      flushPendingHistory: () => calls.push(['flush']),
    },
    emit: (...args) => calls.push(['emit', ...args]),
  }
  const rollbackState = captureInsertedNodeRollbackState(insertedNode, {
    isInserting: true,
    insertionType: 'parent',
  })
  assert.ok(rollbackState)

  assert.equal(rollbackRejectedInsertedNode(
    rollbackState,
    renderer,
    mindMap,
  ), true)
  assert.deepEqual(parentData.children, [childData])
  assert.equal(promotedActivated, true)
  assert.equal(calls.some(item => item[0] === 'unexpected-remove'), false)
  assert.deepEqual(calls.map(item => item[0]), [
    'deactivate',
    'render',
    'history',
    'flush',
    'emit',
  ])
})

test('概要回滚使用持久化 UID 并把选区恢复到所属主题', () => {
  const owner = {
    nodeData: { data: { uid: 'owner' }, children: [] },
    activeCalls: 0,
    active() { this.activeCalls += 1 },
  }
  const nodeData = {
    data: { uid: 'summary-persisted', text: '概要' },
    children: [],
  }
  owner.nodeData.data.generalization = [nodeData.data]
  const summary = {
    uid: 'runtime-summary',
    nodeData,
    isGeneralization: true,
    generalizationBelongNode: owner,
    getData: key => nodeData.data[key],
  }
  nodeData._node = summary
  const state = captureInsertedNodeRollbackState(summary, { isInserting: true })
  let lookedUpUid = ''
  let removed = null
  const renderer = {
    findNodeByUid(uid) {
      lookedUpUid = uid
      return summary
    },
    removeNode(nodes) { removed = nodes },
  }

  assert.equal(rollbackRejectedInsertedNode(
    state,
    renderer,
    { command: { addHistory() {}, flushPendingHistory() {} }, emit() {} },
  ), true)
  assert.equal(lookedUpUid, 'summary-persisted')
  assert.deepEqual(removed, [summary])
  assert.equal(owner.activeCalls, 1)
})

test('远端树已删除待创建概要时拒绝用旧 runtime 误删当前概要', () => {
  const pendingSummaryData = { uid: 'pending-summary', text: '概要 A' }
  const existingSummaryData = { uid: 'existing-summary', text: '概要 B' }
  const oldOwnerData = {
    data: {
      uid: 'owner',
      generalization: [pendingSummaryData, existingSummaryData],
    },
    children: [],
  }
  const ownerRuntime = {
    nodeData: oldOwnerData,
    getData: key => ownerRuntime.nodeData.data[key],
  }
  const pendingSummaryRuntime = {
    nodeData: { data: pendingSummaryData, children: [] },
    isGeneralization: true,
    generalizationBelongNode: ownerRuntime,
    getData: key => pendingSummaryRuntime.nodeData.data[key],
  }
  const state = captureInsertedNodeRollbackState(pendingSummaryRuntime, {
    isInserting: true,
  })
  assert.ok(state)

  // updateData 已同步替换 renderTree 并换绑 owner，但下一帧重建前旧概要
  // runtime 仍留在 _generalizationList/findNodeByUid 中。
  const currentSummaryData = structuredClone(existingSummaryData)
  const currentTree = {
    data: {
      uid: 'owner',
      generalization: [currentSummaryData],
    },
    children: [],
  }
  ownerRuntime.nodeData = currentTree
  ownerRuntime._generalizationList = [
    { generalizationNode: pendingSummaryRuntime },
  ]
  let removeCalls = 0
  const renderer = {
    renderTree: currentTree,
    findNodeByUid: () => pendingSummaryRuntime,
    removeNode() {
      removeCalls += 1
      // 旧实现最终会按旧 runtime 的 index 0 删除当前概要 B。
      currentTree.data.generalization.splice(0, 1)
    },
  }

  assert.equal(rollbackRejectedInsertedNode(
    state,
    renderer,
    { command: {}, emit() {} },
  ), false)
  assert.equal(removeCalls, 0)
  assert.deepEqual(currentTree.data.generalization, [currentSummaryData])
})

test('节点编辑拒绝提示区分占用、连接、只读与服务故障', () => {
  assert.equal(
    getNodeEditLeaseBlockedMessage('occupied', [{ name: '小李' }]),
    '小李正在编辑此节点，请稍后再试',
  )
  assert.match(getNodeEditLeaseBlockedMessage('connecting'), /正在连接/)
  assert.match(getNodeEditLeaseBlockedMessage('readonly'), /只读/)
  assert.match(getNodeEditLeaseBlockedMessage('unavailable'), /服务暂不可用/)
  assert.doesNotMatch(getNodeEditLeaseBlockedMessage('unavailable'), /其他协作者/)
})
