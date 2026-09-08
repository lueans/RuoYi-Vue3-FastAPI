import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  isNodeTextEditOccupied,
  resolveCurrentNodeTextEditTarget,
  shouldBlockNodeTextEditByPresence,
} from '../../libs/simple-mind-map/src/core/render/node/nodeCooperateState.js'
import { getNodeEditLeaseBlockedMessage } from '../mindmap-node-edit-lease.js'

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
  assert.match(showBody, /this\.mindMap\.richText\.showEditText\(params\)[\s\S]*this\.isShowTextEdit\(\)/)
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
