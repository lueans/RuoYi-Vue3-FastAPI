import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import test from 'node:test'

import {
  assertMindmapAiArtifact,
  assertMindmapAiLocalUndoBaseline,
  buildMindmapAiArtifactFromDocument,
  cloneMindmapBranchWithFreshUids,
  computeMindmapDocumentHash,
  computeMindmapSnapshotFingerprint,
  normalizeMindmapAiSourceSnapshot,
} from '../mindmap-ai-artifact.js'

if (!globalThis.crypto) globalThis.crypto = webcrypto

const document = {
  root: {
    data: { uid: 'root', text: '支付系统' },
    children: [],
  },
  layout: 'logicalStructure',
  theme: { template: 'default', config: {} },
  view: null,
  documentData: {},
}

test('浏览器和服务端对 SMM v2 文档计算相同哈希', async () => {
  assert.equal(
    await computeMindmapDocumentHash(document),
    'mmf2:sha256:9a1bc5c1b8266011769e69b28e67bf168d5d99e60f03f692014ef58a382ca697',
  )
  const numericDocument = structuredClone(document)
  numericDocument.root.data.customLeft = 1.0
  numericDocument.root.data.customTop = 1e-7
  assert.equal(
    await computeMindmapDocumentHash(numericDocument),
    'mmf2:sha256:57ce30dda286d5c54bc951c7ef4fddba2810355369ddc5debdaa275d15cef97e',
  )
})

test('本地文件文档可封装为服务端复校验所需的 SMM v2', async () => {
  const artifact = await buildMindmapAiArtifactFromDocument(document, { title: '支付导入' })
  const checked = await assertMindmapAiArtifact(artifact)
  assert.equal(artifact.manifest.title, '支付导入')
  assert.equal(artifact.manifest.sourceType, 'local_import')
  assert.equal(checked.documentHash, artifact.manifest.documentHash)
})

test('插入 AI 分支时重新生成全部 UID 并同步内部引用', () => {
  const branch = {
    data: { uid: 'old-root', text: '分支', associativeLineTargets: ['old-child'] },
    children: [{ data: { uid: 'old-child', text: '子节点' }, children: [] }],
  }
  const cloned = cloneMindmapBranchWithFreshUids(branch)
  assert.notEqual(cloned.data.uid, 'old-root')
  assert.notEqual(cloned.children[0].data.uid, 'old-child')
  assert.equal(cloned.data.associativeLineTargets[0], cloned.children[0].data.uid)
  assert.equal(branch.data.uid, 'old-root')
})

test('AI artifact 在应用前校验格式、状态与哈希', async () => {
  const documentHash = await computeMindmapDocumentHash(document)
  const artifact = {
    format: 'ruoyi-mindmap',
    formatSchemaVersion: 2,
    manifest: {
      validation: { status: 'passed' },
      documentHash,
    },
    document,
  }

  assert.equal((await assertMindmapAiArtifact(artifact)).documentHash, documentHash)
  artifact.document.root.data.text = '已篡改'
  await assert.rejects(() => assertMindmapAiArtifact(artifact), /哈希不匹配/)
})

test('发送给本地基线指纹的快照移除瞬态和事件字段', () => {
  const source = structuredClone(document)
  source.root.data.isActive = true
  source.root.data.onClick = 'alert(1)'
  source.root.smmVersion = '9.9.9-runtime-only'
  source.view = { transform: { scale: 2 } }

  const normalized = normalizeMindmapAiSourceSnapshot(source)
  assert.equal(normalized.root.data.isActive, undefined)
  assert.equal(normalized.root.data.onClick, undefined)
  assert.equal(normalized.root.smmVersion, undefined)
  assert.equal(normalized.view, null)
})

test('新建空白画布与编辑中的空节点会转为稳定来源占位文本', () => {
  const source = structuredClone(document)
  source.root.data.text = '  <b></b>\u0000 '
  source.root.data.note = ' <i></i> '
  source.root.data.hyperlink = '   '

  const normalized = normalizeMindmapAiSourceSnapshot(source)

  assert.equal(normalized.root.data.text, '未命名节点')
  assert.equal(normalized.root.data.note, undefined)
  assert.equal(normalized.root.data.hyperlink, undefined)
})

test('本地 AI 撤销以实际恢复文档复核 root/layout/theme/documentData 基线', async () => {
  const baseline = structuredClone(document)
  baseline.layout = 'mindMap'
  baseline.theme = { template: 'dark', config: { lineColor: '#123456' } }
  baseline.view = { transform: { scale: 1.4, translateX: 23, translateY: -8 } }
  baseline.documentData = {
    custom: { enabled: true, mode: 'strict', schemaVersion: 2 },
  }
  const expectedHash = await computeMindmapSnapshotFingerprint(baseline)

  assert.equal(
    await assertMindmapAiLocalUndoBaseline(structuredClone(baseline), expectedHash),
    expectedHash,
  )

  for (const mutate of [
    value => { value.root.data.text = '被篡改的根节点' },
    value => { value.layout = 'logicalStructure' },
    value => { value.theme.config.lineColor = '#abcdef' },
    value => { value.documentData.custom.mode = 'loose' },
  ]) {
    const changed = structuredClone(baseline)
    mutate(changed)
    await assert.rejects(
      () => assertMindmapAiLocalUndoBaseline(changed, expectedHash),
      error => error?.code === 'AI_LOCAL_UNDO_BASELINE_MISMATCH',
    )
  }
})
