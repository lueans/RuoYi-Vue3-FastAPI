import assert from 'node:assert/strict'
import test from 'node:test'
import {
  mindmapAiDocumentsEqual,
  strictApplyMindmapAiProposal,
  verifyMindmapAiLocalProposal,
} from '../mindmap-ai-proposal.js'
import {
  computeMindmapDocumentHash,
  normalizeMindmapAiSourceSnapshot,
} from '../mindmap-ai-artifact.js'

function document() {
  return {
    root: {
      data: { uid: 'root', text: 'Root', expand: true },
      children: [
        { data: { uid: 'a', text: 'A', note: 'old' }, children: [] },
        {
          data: { uid: 'b', text: 'B' },
          children: [{ data: { uid: 'c', text: 'C' }, children: [] }],
        },
      ],
    },
    layout: 'logicalStructure',
    theme: { template: 'default', config: {} },
    view: null,
    documentData: {},
  }
}

test('严格重放完整操作协议并区分 set 与 unset', () => {
  const result = strictApplyMindmapAiProposal(document(), [
    {
      type: 'delete_subtree', nodeUid: 'c', payload: null,
    },
    {
      type: 'create_node', nodeUid: 'd',
      payload: { parentUid: 'b', index: 0, data: { uid: 'd', text: 'D' } },
    },
    {
      type: 'update_node', nodeUid: 'a',
      payload: { set: { text: 'A2', hyperlink: 'https://example.com' }, unset: ['note'] },
    },
    {
      type: 'move_node', nodeUid: 'a', payload: { parentUid: 'b', index: 1 },
    },
    {
      type: 'set_document_meta', nodeUid: null,
      payload: {
        set: { layout: 'mindMap', documentData: { custom: { enabled: true } } },
        unset: [],
      },
    },
  ])

  assert.equal(result.layout, 'mindMap')
  assert.deepEqual(result.root.children.map(node => node.data.uid), ['b'])
  assert.deepEqual(result.root.children[0].children.map(node => node.data.uid), ['d', 'a'])
  assert.deepEqual(result.root.children[0].children[1].data, {
    uid: 'a', text: 'A2', hyperlink: 'https://example.com',
  })
})

test('失败原子：未知操作、未知字段与不存在 UID 不会修改基线', () => {
  for (const operation of [
    { type: 'unknown', nodeUid: 'a', payload: null },
    {
      type: 'update_node', nodeUid: 'missing',
      payload: { set: { text: 'x' }, unset: [] },
    },
    {
      type: 'update_node', nodeUid: 'a', extra: true,
      payload: { set: { text: 'x' }, unset: [] },
    },
    {
      type: 'update_node', nodeUid: 'a',
      payload: { set: { uid: 'changed' }, unset: [] },
    },
  ]) {
    const baseline = document()
    const frozen = JSON.stringify(baseline)
    assert.throws(() => strictApplyMindmapAiProposal(baseline, [operation]))
    assert.equal(JSON.stringify(baseline), frozen)
  }
})

test('严格拒绝重复 UID、父节点缺失、越界位置、根节点操作与循环移动', () => {
  const invalidCases = [
    {
      type: 'create_node', nodeUid: 'a',
      payload: { parentUid: 'root', index: 0, data: { uid: 'a', text: 'duplicate' } },
    },
    {
      type: 'create_node', nodeUid: 'd',
      payload: { parentUid: 'missing', index: 0, data: { uid: 'd', text: 'D' } },
    },
    {
      type: 'create_node', nodeUid: 'd',
      payload: { parentUid: 'root', index: 99, data: { uid: 'd', text: 'D' } },
    },
    { type: 'move_node', nodeUid: 'root', payload: { parentUid: 'a', index: 0 } },
    { type: 'delete_subtree', nodeUid: 'root', payload: null },
    { type: 'move_node', nodeUid: 'b', payload: { parentUid: 'c', index: 0 } },
  ]
  for (const operation of invalidCases) {
    assert.throws(() => strictApplyMindmapAiProposal(document(), [operation]))
  }
})

test('新增 data.uid 必须绑定 nodeUid，delete payload 必须为 null', () => {
  assert.throws(() => strictApplyMindmapAiProposal(document(), [{
    type: 'create_node', nodeUid: 'd',
    payload: { parentUid: 'root', index: 0, data: { uid: 'other', text: 'D' } },
  }]), /不一致/)
  assert.throws(() => strictApplyMindmapAiProposal(document(), [{
    type: 'delete_subtree', nodeUid: 'a', payload: {},
  }]), /必须为 null/)
})

test('文档比较使用稳定键顺序', () => {
  assert.equal(mindmapAiDocumentsEqual({ b: 1, a: { d: 2, c: 3 } }, {
    a: { c: 3, d: 2 }, b: 1,
  }), true)
})

test('本地应用要求 operations、proposal hash 与 artifact hash 三方一致', async () => {
  const baseline = document()
  const operations = [{
    type: 'update_node', nodeUid: 'a',
    payload: { set: { text: 'A2' }, unset: ['note'] },
  }]
  const expected = strictApplyMindmapAiProposal(baseline, operations)
  const baseHash = await computeMindmapDocumentHash(baseline)
  const resultHash = await computeMindmapDocumentHash(expected)
  const verified = await verifyMindmapAiLocalProposal({
    baseDocument: baseline,
    operations,
    baseHash,
    resultHash,
    artifactDocument: expected,
    artifactHash: resultHash,
  })
  assert.deepEqual(verified.document, expected)

  for (const override of [
    { resultHash: `mmf2:sha256:${'1'.repeat(64)}` },
    { artifactHash: `mmf2:sha256:${'2'.repeat(64)}` },
    { artifactDocument: { ...expected, layout: 'mindMap' } },
    {
      operations: [{
        type: 'update_node', nodeUid: 'a',
        payload: { set: { text: 'tampered' }, unset: ['note'] },
      }],
    },
  ]) {
    await assert.rejects(() => verifyMindmapAiLocalProposal({
      baseDocument: baseline,
      operations,
      baseHash,
      resultHash,
      artifactDocument: expected,
      artifactHash: resultHash,
      ...override,
    }), /提案/)
  }
})

test('本地应用保留未修改节点的富文本字节和视图状态', async () => {
  const baseline = document()
  baseline.root.data.text = '<p><span>Root</span></p>'
  baseline.root.data.richText = true
  baseline.root.children[0].data.text = '<p><strong>A</strong></p>'
  baseline.root.children[0].data.richText = true
  baseline.view = { transform: { scale: 1.25, x: 10, y: 20 } }
  const operations = [{
    type: 'create_node', nodeUid: 'created',
    payload: {
      parentUid: 'root', index: 2,
      data: { uid: 'created', text: 'AI 新增' },
    },
  }]
  const normalizedBaseline = normalizeMindmapAiSourceSnapshot(baseline)
  const artifact = strictApplyMindmapAiProposal(normalizedBaseline, operations)
  const baseHash = await computeMindmapDocumentHash(normalizedBaseline)
  const resultHash = await computeMindmapDocumentHash(artifact)

  const verified = await verifyMindmapAiLocalProposal({
    baseDocument: baseline,
    operations,
    baseHash,
    resultHash,
    artifactDocument: artifact,
    artifactHash: resultHash,
  })

  assert.equal(verified.document.root.data.text, '<p><span>Root</span></p>')
  assert.equal(verified.document.root.children[0].data.text, '<p><strong>A</strong></p>')
  assert.deepEqual(verified.document.view, baseline.view)
  assert.equal(verified.document.root.children[2].data.text, 'AI 新增')
})
