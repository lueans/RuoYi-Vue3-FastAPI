import assert from 'node:assert/strict'
import test from 'node:test'
import { createMindmapAiTemplateAttachment } from '../mindmap-ai-templates.js'
import { validateMindmapAiAttachments } from '../mindmap-ai-attachments.js'

const customStyle = {
  fill: '#fedcba', color: '#123456', fontSize: 18, radius: 4, paddingX: 12,
  placement: 'top', align: 'left', iconKey: 'priority_1',
}

function template(tag = { tagId: 7, tagKey: 'important', text: '重要', style: customStyle }) {
  return {
    id: 12, contentRevision: 3, name: '测试用例模版',
    nodeTree: {
      data: { uid: 'root', text: '测试用例' },
      children: [{ data: { uid: 'case', text: '用例名称', note: '填写预期结果', tag: [tag] }, children: [] }],
    },
  }
}

test('模版附件携带对应节点的标签身份、自定义样式和局部位置，源脑图不变', async () => {
  const input = template({
    tagId: 7, tagKey: 'important', text: '重要', style: customStyle,
    placement: 'right', align: 'bottom', internalMetadata: 'not reference content',
  })
  const before = structuredClone(input)
  const result = await createMindmapAiTemplateAttachment(input)
  assert.equal(result.text, '- 示例节点：测试用例\n  - 示例节点：用例名称\n    示例备注：填写预期结果\n    标签：' + JSON.stringify([{
    tagId: 7, tagKey: 'important', text: '重要', style: customStyle, placement: 'right', align: 'bottom',
  }]))
  assert.equal(result.purpose, 'template')
  assert.deepEqual(result.templateSource, { mindmapId: 12, contentRevision: 3 })
  assert.equal(result.size, new TextEncoder().encode(result.text).byteLength)
  assert.deepEqual(input, before)
})

test('云端模版引用只携带身份和版本，拒绝不精确身份或客户端伪造格式', async () => {
  const result = await createMindmapAiTemplateAttachment(template())
  assert.throws(() => validateMindmapAiAttachments([{ ...result, templateSource: {
    ...result.templateSource, style: { fillColor: '#ff0000' },
  } }]), /模版来源或版本无效/u)
  assert.throws(() => validateMindmapAiAttachments([{ ...result, purpose: 'reference' }]), /模版来源或版本无效/u)
  for (const changes of [{ mindmapId: 0 }, { mindmapId: true }, { contentRevision: -1 }]) {
    assert.throws(() => validateMindmapAiAttachments([{ ...result, templateSource: {
      ...result.templateSource, ...changes,
    } }]), /模版来源或版本无效/u)
  }
  await assert.rejects(createMindmapAiTemplateAttachment({ ...template(), id: '9007199254740993' }), /脑图信息不完整/u)
})

test('标签样式变化更新模版内容身份，避免复用旧样式的本轮请求', async () => {
  const first = await createMindmapAiTemplateAttachment(template())
  const same = await createMindmapAiTemplateAttachment(template())
  const changed = template()
  changed.nodeTree.children[0].data.tag[0].style = { ...customStyle, fill: '#aabbcc' }
  const second = await createMindmapAiTemplateAttachment(changed)
  assert.equal(first.id, same.id)
  assert.notEqual(first.id, second.id)
  assert.match(second.text, /"fill":"#aabbcc"/u)
})

test('模版深度按根节点为第一层计算，仅作为附件展示元数据', async () => {
  const input = template()
  let parent = input.nodeTree.children[0]
  for (let depth = 3; depth <= 7; depth += 1) {
    const child = { data: { uid: `depth-${depth}`, text: `第${depth}层` }, children: [] }
    parent.children.push(child)
    parent = child
  }
  const result = await createMindmapAiTemplateAttachment(input)
  assert.equal(result.templateDepth, 7)
  assert.doesNotMatch(result.text, /templateDepth/)
  input.nodeTree.children = []
  assert.equal((await createMindmapAiTemplateAttachment(input)).templateDepth, 1)
})

test('旧字符串标签仅传可读名称，无效身份不会变成可绑定的标签 ID', async () => {
  const input = template()
  input.nodeTree.children[0].data.tag = ['旧标签', { tagId: -1, text: '无效身份' }, null, {}]
  const result = await createMindmapAiTemplateAttachment(input)
  assert.ok(result.text.endsWith('标签：[{"text":"旧标签"},{"text":"无效身份"}]'))
})

test('模版文字和备注明确标记为示例，同时保留节点关系', async () => {
  const input = template()
  delete input.nodeTree.children[0].data.tag
  const result = await createMindmapAiTemplateAttachment(input)
  assert.equal(result.text, '- 示例节点：测试用例\n  - 示例节点：用例名称\n    示例备注：填写预期结果')
})

test('只有节点关系和标签样式的模版无需预先填写内容', async () => {
  const input = template()
  input.nodeTree.data.text = ''
  input.nodeTree.children[0].data.text = ''
  delete input.nodeTree.children[0].data.note
  const result = await createMindmapAiTemplateAttachment(input)
  assert.ok(result.text.startsWith('- 示例节点：（未填写示例）\n  - 示例节点：（未填写示例）\n    标签：'))
  assert.match(result.text, /"tagId":7/u)
  assert.match(result.text, /"fill":"#fedcba"/u)
})

test('无效标签样式明确报错，样式内容也计入模版长度上限', async () => {
  await assert.rejects(createMindmapAiTemplateAttachment(template({
    tagId: 7, text: '重要', style: { fill: 'url(https://example.com)' },
  })), /标签样式无效/u)
  const input = template()
  input.nodeTree.data.text = '字'.repeat(49_990)
  input.nodeTree.children = []
  input.nodeTree.data.tag = [{ tagId: 7, text: '重要', style: customStyle }]
  await assert.rejects(createMindmapAiTemplateAttachment(input), /50,000/u)
})
