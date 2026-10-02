import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript, babelParse } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'
import * as Vue from 'vue'
import { buildMindmapAiAttachmentMetadata } from '../mindmap-ai-attachment-records.js'

const descriptor = parse(readFileSync(new URL('../../components/MindMap/MindmapAgentAttachmentRecords.vue', import.meta.url), 'utf8')).descriptor
const code = compileScript(descriptor, { id: 'attachment-records-test', inlineTemplate: true }).content
const bindings = { buildMindmapAiAttachmentMetadata }, body = []
for (const node of babelParse(code, { sourceType: 'module' }).program.body) {
  if (node.type === 'ImportDeclaration') {
    for (const specifier of node.specifiers) {
      bindings[specifier.local.name] = node.source.value === 'vue'
        ? Vue[specifier.imported.name] : bindings[specifier.local.name]
      assert.ok(bindings[specifier.local.name], `Missing production dependency: ${specifier.local.name}`)
    }
  } else if (node.type === 'ExportDefaultDeclaration') body.push(`return ${code.slice(node.declaration.start, node.declaration.end)}`)
  else body.push(code.slice(node.start, node.end))
}
const Component = new Function(...Object.keys(bindings), body.join('\n'))(...Object.values(bindings))
const render = attachments => renderToString(Vue.createSSRApp(Component, { attachments }))
const attachment = (overrides = {}) => ({ id: 'file', name: '需求.txt', size: 128, mediaType: 'text/plain', ...overrides })

test('local parsing receipts count Unicode code points and retain the full extracted whitespace', () => {
  for (const [text, characterCount] of [['A中😀', 3], ['\n😀 e\u0301\t', 6], ['𠮷'.repeat(50_000), 50_000]]) {
    const [metadata] = buildMindmapAiAttachmentMetadata([attachment({ text })])
    assert.deepEqual(metadata.parsing, { status: 'parsed', characterCount })
    assert.ok(!Object.hasOwn(metadata, 'text'))
  }
  const [overLimit] = buildMindmapAiAttachmentMetadata([attachment({ text: '😀'.repeat(50_001) })])
  assert.deepEqual(overLimit.parsing, { status: 'unknown' })
})

test('receipts are independent metadata snapshots that never retain extracted text or extra parser fields', () => {
  const original = attachment({ text: 'PRIVATE_ATTACHMENT_BODY😀', status: 'ready',
    content: 'PRIVATE_CONTENT_FIELD', parsing: { status: 'parsed', characterCount: 999, content: 'PRIVATE_PARSER_BODY', html: '<b>untrusted</b>' },
    modelRead: true, ocr: { text: 'PRIVATE_OCR_BODY' } })
  const result = buildMindmapAiAttachmentMetadata([original])
  assert.deepEqual(result, [attachment({ parsing: { status: 'parsed', characterCount: 24 } })])
  original.name = '后来改名.txt'
  original.text = '新内容'
  original.parsing.characterCount = 1
  assert.equal(result[0].name, '需求.txt')
  assert.equal(result[0].parsing.characterCount, 24)
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE_|untrusted|modelRead|ocr|"text"|"content"|"html"/)
})

test('bounded server receipts survive a body-free round trip without trusting extra metadata', () => {
  for (const characterCount of [1, 50_000]) {
    const [metadata] = buildMindmapAiAttachmentMetadata([attachment({ parsing: {
      status: 'parsed', characterCount, message: 'PRIVATE_REMOTE_NOTE', html: '<script>alert(1)</script>',
    } })])
    assert.deepEqual(metadata.parsing, { status: 'parsed', characterCount })
    assert.deepEqual(buildMindmapAiAttachmentMetadata(JSON.parse(JSON.stringify([metadata]))), [metadata])
    assert.doesNotMatch(JSON.stringify(metadata), /PRIVATE_REMOTE_NOTE|script|html|message/)
  }
})

test('legacy files and malformed receipts remain unknown instead of claiming successful parsing', () => {
  const inputs = [
    {}, { status: 'ready' }, { parsing: null }, { parsing: 'parsed' }, { parsing: { status: 'parsed' } },
    ...[0, -1, 50_001, 1.5, NaN, Infinity, '42', null].map(characterCount => ({ parsing: { status: 'parsed', characterCount } })),
    { parsing: { status: 'failed', characterCount: 42 } },
    ...['', ' \n\t ', null, 42].map(text => ({ text, parsing: { status: 'parsed', characterCount: 42 } })),
  ]
  for (const input of inputs) {
    const [metadata] = buildMindmapAiAttachmentMetadata([attachment(input)])
    assert.deepEqual(metadata.parsing, { status: 'unknown' }, JSON.stringify(input))
  }
})

test('metadata accepts only display fields with bounded lengths and a maximum of five files', () => {
  const [metadata] = buildMindmapAiAttachmentMetadata([attachment({
    id: 'i'.repeat(101), name: 'n'.repeat(256), mediaType: 'm'.repeat(129), size: -1,
  })])
  assert.equal(metadata.id.length, 100)
  assert.equal(metadata.name.length, 255)
  assert.equal(metadata.mediaType.length, 128)
  assert.equal(metadata.size, undefined)
  for (const input of [undefined, null, {}, 'files', [null, {}, { name: '' }, { name: ' \t' }, { name: 12 }]]) {
    assert.deepEqual(buildMindmapAiAttachmentMetadata(input), [])
  }
  assert.deepEqual(buildMindmapAiAttachmentMetadata(Array.from({ length: 6 }, (_, index) => attachment({ id: String(index) }))).map(file => file.id), ['0', '1', '2', '3', '4'])
})

test('production records component renders a closed native disclosure with receipt counts and precise limitations', async () => {
  const html = await render([
    attachment({ id: 'parsed', text: '😀'.repeat(1234) }),
    attachment({ id: 'legacy', name: '旧附件.pdf', size: 9999 }),
  ])
  assert.match(html, /aria-label="文件解析记录"/)
  assert.match(html, /<details>/)
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/)
  assert.match(html, /<summary>文件解析记录 <span>1\/2 个已解析<\/span><\/summary>/)
  assert.equal((html.match(/<li>/g) || []).length, 2)
  assert.match(html, /文本提取完成 · 1,234 字符/)
  assert.match(html, /解析记录不可用/)
  assert.match(html, /不代表 AI 已阅读/)
  assert.match(html, /不包含图片识别结果/)
  assert.doesNotMatch(html, /😀|9999|9,999/)
})

test('production records component escapes file names and ignores malicious parser metadata and attachment bodies', async () => {
  const html = await render([attachment({
    name: '<img src=x onerror="attack()"> & 需求.pdf', text: 'PRIVATE_ATTACHMENT_BODY😀',
    parsing: { status: '<script>BAD_STATUS</script>', characterCount: '<svg onload=attack()>', html: 'PRIVATE_HTML', note: 'PRIVATE_NOTE' },
    content: 'PRIVATE_CONTENT', url: 'javascript:attack()', modelRead: 'UNVERIFIED_READ',
  }), attachment({ id: 'bad-count', name: '无效记录.txt', parsing: { status: 'parsed', characterCount: '<script>BAD_COUNT</script>' } })])
  assert.match(html, /title="&lt;img src=x onerror=&quot;attack\(\)&quot;&gt; &amp; 需求.pdf"/)
  assert.match(html, /&lt;img src=x onerror=&quot;attack\(\)&quot;&gt; &amp; 需求.pdf<\/span>/)
  assert.match(html, /1\/2 个已解析/)
  assert.match(html, /文本提取完成 · 24 字符/)
  assert.match(html, /解析记录不可用/)
  assert.doesNotMatch(html, /<img|<script|<svg|PRIVATE_|BAD_STATUS|BAD_COUNT|javascript:|UNVERIFIED_READ/)
})

test('production records component hides absent files and displays no more than five receipts', async () => {
  for (const attachments of [undefined, [], [null, { name: '' }]]) {
    const html = await render(attachments)
    assert.doesNotMatch(html, /<section|<details|文件解析记录/)
  }
  const html = await render(Array.from({ length: 6 }, (_, index) => attachment({
    id: String(index), name: `附件${index + 1}.txt`, parsing: { status: 'parsed', characterCount: index + 1 },
  })))
  assert.equal((html.match(/<li>/g) || []).length, 5)
  assert.match(html, /5\/5 个已解析/)
  assert.doesNotMatch(html, /附件6/)
})

test('server template warnings remain visible outside collapsed details and never become HTML or upload instructions', async () => {
  const warning = '模版中的部分标签当前不可引用，已跳过这些标签：紧急'
  const file = attachment({ purpose: 'template', warnings: [warning, warning, '<img src=x onerror=attack()>'],
    parsing: { status: 'parsed', characterCount: 7 } })
  const [metadata] = buildMindmapAiAttachmentMetadata([file])
  assert.deepEqual(metadata.warnings, [warning, '<img src=x onerror=attack()>'])
  assert.deepEqual(buildMindmapAiAttachmentMetadata([metadata]), [metadata])
  const html = await render([file])
  assert.ok(html.indexOf(warning) < html.indexOf('<details>'))
  assert.match(html, /role="status"/)
  assert.doesNotMatch(html, /<img|<details[^>]*\bopen\b/)
  for (const input of [attachment({ warnings: [warning] }), { ...file, text: 'client data' }]) {
    assert.equal(buildMindmapAiAttachmentMetadata([input])[0].warnings, undefined)
  }
  const bounded = buildMindmapAiAttachmentMetadata([{ ...file, warnings: [null, {}, '', ...Array.from({ length: 8 }, (_, index) => `${index}${'😀'.repeat(700)}`)] }])[0]
  assert.equal(bounded.warnings.length, 5)
  assert.ok(bounded.warnings.every(value => Array.from(value).length === 500))
})
