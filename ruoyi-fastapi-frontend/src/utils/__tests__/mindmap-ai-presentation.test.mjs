import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive, isProxy } from 'vue'
import { applyMindmapAiPresentationFrame, clearMindmapAiPresentation, renderMindmapAiPreviewTree } from '../mindmap-ai-presentation.js'

const document = text => ({ root: { data: { uid: 'root', text }, children: [] } })
test('真实 Vue 草稿代理在结构帧边界安全克隆，全文目标不进入正文', async () => {
  let received
  const mindMap = {
    renderer: { setData: root => { received = root }, findNodeByUid: () => null },
    renderAsync: callback => callback(),
  }
  const target = reactive(document('第'))
  await applyMindmapAiPresentationFrame(mindMap, document('旧'), {
    document: target, typewriterTarget: { uid: 'root', text: '第一个节点' },
  })
  assert.equal(received.data.text, '第')
  assert.equal(isProxy(received), false)
  assert.equal(isProxy(received.data), false)
  assert.equal(mindMap.renderer.textRevealTargets.get('root').text, '第一个节点')
})

test('字符帧只推进现有文本呈现器，不重新渲染或重建树', async () => {
  let revealed
  const node = {
    nodeData: document('第').root,
    _textData: { reveal: { targetText: '第一个节点', setVisible: text => { revealed = text } } },
    getData() { return this.nodeData.data },
    reRender() { assert.fail('character frame must not recreate the node') },
  }
  const mindMap = {
    renderer: { findNodeByUid: () => node, setData: () => assert.fail('must not replace tree') },
  }
  await applyMindmapAiPresentationFrame(mindMap, document('第'), {
    document: document('第一'), typewriterTarget: { uid: 'root', text: '第一个节点' },
  })
  assert.equal(revealed, '第一')
  assert.equal(node.nodeData.data.text, '第一')
  assert.equal(JSON.parse(node.nodeDataSnapshot).text, '第一')
})

test('字符快路径不索引或序列化共享的未变子树', async () => {
  let untouchedReads = 0
  const shared = {
    get data() { untouchedReads++; return { uid: 'shared', text: '保持' } },
    children: Array.from({ length: 1000 }, (_, index) => ({
      get data() { untouchedReads++; return { uid: `shared-${index}`, text: '保持' } },
      children: [],
    })),
  }
  const before = { root: { data: { uid: 'parent', text: '根' }, children: [document('第').root, shared] } }
  const after = { root: { ...before.root, children: [document('第一').root, shared] } }
  let revealed
  const runtime = {
    nodeData: document('第').root,
    _textData: { reveal: { targetText: '第一个节点', setVisible: text => { revealed = text } } },
    getData() { return this.nodeData.data },
  }
  const map = { renderer: {
    findNodeByUid: uid => uid === 'root' ? runtime : null,
    setData: () => assert.fail('shared subtrees must not force a structural render'),
  } }
  await applyMindmapAiPresentationFrame(map, before, {
    document: after, typewriterTarget: { uid: 'root', text: '第一个节点' },
  })
  assert.equal(revealed, '第一')
  assert.equal(untouchedReads, 0, 'shared subtrees and their descendants are skipped before reading data')
})

test('结构、业务字段或第二处文字同时改变时不能误用单字快路径', async () => {
  const node = (uid, text) => ({ data: { uid, text }, children: [] })
  const before = { root: { data: { uid: 'parent', text: '根' }, children: [node('a', '第'), node('b', '保留')] } }
  const variants = [
    [node('b', '保留'), node('a', '第一')],
    [node('a', '第一'), node('b', '其他变化')],
    [node('a', '第一'), { ...node('b', '保留'), data: { uid: 'b', text: '保留', note: '新增备注' } }],
    [node('a', '第一'), node('b', '保留'), node('c', '新')],
    [node('a', '第一')],
  ]
  for (const children of variants) {
    let received
    const after = { root: { ...before.root, children } }
    const map = {
      renderer: {
        findNodeByUid: () => assert.fail('a multi-field frame is not a single-text delta'),
        setData: root => { received = root },
      },
      renderAsync: done => done(),
    }
    await applyMindmapAiPresentationFrame(map, before, {
      document: after, typewriterTarget: { uid: 'a', text: '第一个节点' },
    })
    assert.deepEqual(received, after.root)
    assert.notEqual(received, after.root)
  }
})

test('单字差异复用祖先路径时仍临时展开折叠父节点且不修改正文', async () => {
  const before = { root: { data: { uid: 'parent', text: '根', expand: false }, children: [document('第').root] } }
  const after = { root: { ...before.root, children: [document('第一').root] } }
  let received
  const map = {
    renderer: { findNodeByUid: () => null, setData: root => { received = root } },
    renderAsync: done => done(),
  }
  await applyMindmapAiPresentationFrame(map, before, {
    document: after, typewriterTarget: { uid: 'root', text: '第一个节点' },
  })
  assert.deepEqual([...map.renderer.aiPresentationExpandedNodeUids], ['parent'])
  assert.equal(received.data.expand, false)
  assert.equal(before.root.data.expand, false)
  assert.equal(after.root.data.expand, false)
})

test('渲染错误必须拒绝帧，不伪造成功 ACK', async () => {
  await assert.rejects(renderMindmapAiPreviewTree({ renderer: {
    setData() { throw new Error('renderer failed') },
  } }, document('第').root), /renderer failed/)
})

for (const phase of ['first-character', 'reveal']) {
  test(`${phase} 快路径异常后重试必须重建而非确认未挂载的文本`, async () => {
    const target = '新的完整文字'
    let rebuilt = 0
    const runtime = {
      nodeData: document('旧文字').root,
      getData() { return this.nodeData.data },
      reRender() {
        this._textData = { reveal: { targetText: target, setVisible() { assert.fail('detached reveal reused') } } }
        throw new Error('layout failed after creating detached text')
      },
    }
    if (phase === 'reveal') runtime._textData = { reveal: { targetText: target, setVisible() { throw new Error('reveal failed') } } }
    const map = {
      renderer: { findNodeByUid: () => runtime, setData() { rebuilt++ } },
      renderAsync(done) { this.renderer.renderRecoveryRequired = false; done() },
    }
    const frame = { document: document('新'), typewriterTarget: { uid: 'root', text: target } }
    await assert.rejects(applyMindmapAiPresentationFrame(map, document('旧文字'), frame), /failed/)
    assert.equal(map.renderer.renderRecoveryRequired, true)
    await applyMindmapAiPresentationFrame(map, document('旧文字'), frame)
    assert.equal(rebuilt, 1)
    assert.equal(map.renderer.renderRecoveryRequired, false)
  })
}

test('渲染器异步错误回执立即拒绝，迟到成功回调不能改为成功', async () => {
  let success
  let fail
  const map = { renderer: { setData() {} }, renderAsync: (done, _source, rejected) => { success = done; fail = rejected } }
  const result = renderMindmapAiPreviewTree(map, document('第').root)
  fail(new Error('asynchronous layout failed'))
  await assert.rejects(result, /asynchronous layout failed/)
  success()
  await assert.rejects(result, /asynchronous layout failed/)
})

test('临时展开不修改文档字段，跨帧保留覆盖状态', async () => {
  const root = { data: { uid: 'parent', text: '父', expand: false }, children: [document('第').root] }
  let received
  const map = {
    renderer: { setData: tree => { received = tree }, findNodeByUid: () => null },
    renderAsync: callback => callback(),
  }
  await applyMindmapAiPresentationFrame(map, { root: { ...root, children: [] } }, {
    document: { root }, typewriterTarget: { uid: 'root', text: '第一节点' },
  })
  assert.equal(root.data.expand, false)
  assert.equal(received.data.expand, false)
  assert.deepEqual([...map.renderer.aiPresentationExpandedNodeUids], ['parent'])
  await clearMindmapAiPresentation(map)
  assert.equal(map.renderer.aiPresentationExpandedNodeUids.size, 0)
  assert.equal(map.renderer.aiPresentationVisibilityRestorePending, false)
})

test('清理恢复渲染失败必须保留重试义务，不能因集合已清空而跳过恢复', async () => {
  let attempts = 0
  const map = {
    renderer: { aiPresentationExpandedNodeUids: new Set(['parent']) },
    renderAsync: (done, _source, fail) => { if (++attempts === 1) fail(new Error('cleanup failed')); else done() },
  }
  await assert.rejects(clearMindmapAiPresentation(map), /cleanup failed/)
  assert.equal(map.renderer.aiPresentationExpandedNodeUids.size, 0)
  assert.equal(map.renderer.aiPresentationVisibilityRestorePending, true)
  await clearMindmapAiPresentation(map)
  assert.equal(attempts, 2)
  assert.equal(map.renderer.aiPresentationVisibilityRestorePending, false)
})

test('render:false 同步取消旧清理，新会话覆盖不能被迟到成功回调清除', async () => {
  let completeOld
  let cancelled = 0
  const map = {
    renderer: { aiPresentationExpandedNodeUids: new Set(['old-parent']) },
    renderAsync: (done, _source, fail) => {
      completeOld = done
      return { cancel(error) { cancelled++; fail(error) } }
    },
  }
  const oldCleanup = clearMindmapAiPresentation(map)
  const rejected = assert.rejects(oldCleanup, /新会话替代/)
  const detached = clearMindmapAiPresentation(map, { render: false })
  assert.equal(cancelled, 1)
  map.renderer.aiPresentationExpandedNodeUids.add('new-parent')
  completeOld()
  await detached
  await rejected
  assert.deepEqual([...map.renderer.aiPresentationExpandedNodeUids], ['new-parent'])
  assert.equal(map.renderer.aiPresentationVisibilityRestorePending, true)
})
