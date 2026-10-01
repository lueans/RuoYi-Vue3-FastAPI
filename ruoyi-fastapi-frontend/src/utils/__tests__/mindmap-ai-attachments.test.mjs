import assert from 'node:assert/strict'
import test from 'node:test'
import JSZip from 'jszip'
import { PDFDocument, PDFName, PDFString, StandardFonts } from 'pdf-lib'
import {
  MAX_MINDMAP_AI_ATTACHMENT_BYTES,
  MAX_MINDMAP_AI_ATTACHMENT_CHARS,
  MINDMAP_AI_ATTACHMENT_ACCEPT,
  readMindmapAiAttachment,
  validateMindmapAiAttachments,
} from '../mindmap-ai-attachments.js'
import { formatAttachmentSize } from '../mindmap-ai-attachment-records.js'

function file(name, content, type = '') {
  return new File([content], name, { type })
}

async function makeDocx(text = '需求说明 & acceptance criteria') {
  const zip = new JSZip()
  zip.file('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
  zip.file('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
  zip.file('word/document.xml', `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>${text.replaceAll('&', '&amp;').replaceAll('<', '&lt;')}</w:t></w:r></w:p></w:body></w:document>`)
  return zip
}

async function docxFile(zip) {
  return file('需求.docx', await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' }))
}

async function pdfFile(text = '', pageCount = 1) {
  const pdf = await PDFDocument.create()
  const font = await pdf.embedFont(StandardFonts.Helvetica)
  for (let page = 0; page < pageCount; page += 1) {
    const canvas = pdf.addPage()
    if (text) canvas.drawText(text, { font, x: 20, y: 800, size: 1, maxWidth: 550, lineHeight: 2 })
  }
  return file('requirements.pdf', await pdf.save())
}

test('支持的附件格式与文件选择器一致，不宣称支持旧 DOC 或图片', () => {
  assert.equal(MINDMAP_AI_ATTACHMENT_ACCEPT, '.txt,.md,.markdown,.json,.csv,.pdf,.docx')
})

test('TXT/Markdown/JSON/CSV 保留原始文字，并根据文件扩展名确定 MIME', async () => {
  const text = '登录场景\n  - 保留缩进、<标签> 与 & 符号\n'
  for (const [extension, mime] of Object.entries({ txt: 'text/plain', md: 'text/markdown', markdown: 'text/markdown', json: 'application/json', csv: 'text/csv' })) {
    const result = await readMindmapAiAttachment(file(`需求.${extension.toUpperCase()}`, text, 'application/octet-stream'))
    assert.equal(result.text, text)
    assert.equal(result.mediaType, mime)
    assert.equal(result.name, `需求.${extension.toUpperCase()}`)
    assert.equal(result.size, new TextEncoder().encode(text).length)
    assert.match(result.id, /^attachment-[a-f0-9]{64}$/u)
    assert.equal(validateMindmapAiAttachments([result]), true)
  }
})

test('相同附件重复选择生成稳定 ID，不同内容或名称产生不同 ID', async () => {
  const first = await readMindmapAiAttachment(file('a.txt', 'hello'))
  assert.equal((await readMindmapAiAttachment(file('a.txt', 'hello'))).id, first.id)
  assert.notEqual((await readMindmapAiAttachment(file('b.txt', 'hello'))).id, first.id)
  assert.notEqual((await readMindmapAiAttachment(file('a.txt', 'world'))).id, first.id)
})

test('UTF-8 BOM 和 UTF-16 BOM 可读取，未知编码明确报错', async () => {
  assert.equal((await readMindmapAiAttachment(file('bom.txt', '\ufeff中文'))).text, '中文')
  const utf16 = new Uint8Array([0xff, 0xfe, 0x2d, 0x4e, 0x87, 0x65])
  assert.equal((await readMindmapAiAttachment(file('utf16.txt', utf16))).text, '中文')
  await assert.rejects(readMindmapAiAttachment(file('gbk.txt', new Uint8Array([0xd6, 0xd0]))), /UTF-8/u)
})

test('空文件、纯空白和伪装文本的二进制文件不会上传', async () => {
  await assert.rejects(readMindmapAiAttachment(file('empty.txt', '')), /空文件/u)
  await assert.rejects(readMindmapAiAttachment(file('space.md', ' \n\t')), /未读取到可用文字/u)
  await assert.rejects(readMindmapAiAttachment(file('binary.txt', 'a\0b')), /二进制/u)
  await assert.rejects(readMindmapAiAttachment(file('old.doc', 'fake')), /暂不支持/u)
  await assert.rejects(readMindmapAiAttachment(file('image.png', 'fake')), /暂不支持/u)
})

test('文件大小在读取前限制为 10 MiB，并检测读取不完整', async () => {
  let read = false
  await assert.rejects(readMindmapAiAttachment({ name: 'big.txt', size: MAX_MINDMAP_AI_ATTACHMENT_BYTES + 1, arrayBuffer() { read = true } }), /10 MB/u)
  assert.equal(read, false)
  await assert.rejects(readMindmapAiAttachment({ name: 'bad.txt', size: 2, arrayBuffer: async () => new ArrayBuffer(1) }), /读取不完整/u)
})

test('单附件 50,000 字符边界严格校验，绝不截断正文', async () => {
  const full = '中'.repeat(MAX_MINDMAP_AI_ATTACHMENT_CHARS)
  assert.equal((await readMindmapAiAttachment(file('full.txt', full))).text, full)
  await assert.rejects(readMindmapAiAttachment(file('too-long.txt', full + '中')), /50,000/u)
})

test('数量与总文字限制覆盖累积添加附件', async () => {
  const small = await readMindmapAiAttachment(file('small.txt', 'x'))
  assert.equal(validateMindmapAiAttachments(Array(5).fill(small)), true)
  assert.throws(() => validateMindmapAiAttachments(Array(6).fill(small)), /5 个附件/u)
  const full = await readMindmapAiAttachment(file('full.txt', 'x'.repeat(50_000)))
  assert.equal(validateMindmapAiAttachments([full, full]), true)
  assert.throws(() => validateMindmapAiAttachments([full, full, small]), /100,000/u)
  assert.throws(() => validateMindmapAiAttachments(null), /附件列表/u)
})

test('附件大小展示不依赖浏览器', () => {
  assert.equal(formatAttachmentSize(125), '125 B')
  assert.equal(formatAttachmentSize(1024), '1 KB')
  assert.equal(formatAttachmentSize(1536), '2 KB')
  assert.equal(formatAttachmentSize(1024 ** 2), '1 MB')
  assert.equal(formatAttachmentSize(1024 ** 2 * 1.5), '1.5 MB')
})

test('真实 PDF 提取正文及页间分隔符', async () => {
  const result = await readMindmapAiAttachment(await pdfFile('Login acceptance criteria', 2))
  assert.equal(result.mediaType, 'application/pdf')
  assert.equal(result.text, 'Login acceptance criteria\n\nLogin acceptance criteria')
})

test('中文 PDF 依据 ToUnicode 字符映射读取中文，不把 UTF-16 编码当作乱码', async () => {
  const pdf = await PDFDocument.create()
  const page = pdf.addPage()
  const mapping = pdf.context.register(pdf.context.stream('/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n2 beginbfchar\n<0001> <4E2D>\n<0002> <6587>\nendbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend'))
  const descriptor = pdf.context.register(pdf.context.obj({
    Type: 'FontDescriptor', FontName: 'TestCJK', Flags: 4, FontBBox: [0, -200, 1000, 900],
    ItalicAngle: 0, Ascent: 880, Descent: -120, CapHeight: 880, StemV: 80,
  }))
  const descendant = pdf.context.register(pdf.context.obj({
    Type: 'Font', Subtype: 'CIDFontType2', BaseFont: 'TestCJK',
    CIDSystemInfo: { Registry: PDFString.of('Adobe'), Ordering: PDFString.of('Identity'), Supplement: 0 },
    FontDescriptor: descriptor, DW: 1000,
  }))
  const font = pdf.context.register(pdf.context.obj({
    Type: 'Font', Subtype: 'Type0', BaseFont: 'TestCJK', Encoding: 'Identity-H',
    DescendantFonts: [descendant], ToUnicode: mapping,
  }))
  page.node.set(PDFName.of('Resources'), pdf.context.obj({ Font: { F1: font } }))
  page.node.set(PDFName.of('Contents'), pdf.context.register(pdf.context.stream('BT /F1 12 Tf 50 750 Td <00010002> Tj ET')))
  const result = await readMindmapAiAttachment(file('中文.pdf', await pdf.save()))
  assert.equal(result.text, '中文')
})

test('无文本 PDF 提示扫描件 OCR，损坏 PDF 和超过 100 页明确拒绝', async () => {
  await assert.rejects(readMindmapAiAttachment(await pdfFile()), /OCR/u)
  await assert.rejects(readMindmapAiAttachment(file('bad.pdf', '%PDF-1.7\nbroken')), /PDF 无法解析/u)
  await assert.rejects(readMindmapAiAttachment(await pdfFile('Text', 101)), /100 页/u)
})

test('PDF 大量文字超过限制时报错，不返回前 50,000 字符', async () => {
  await assert.rejects(readMindmapAiAttachment(await pdfFile('Long document '.repeat(2000), 2)), /50,000/u)
})

test('真实 DOCX 提取段落文字并保留实体对应的字符', async () => {
  const result = await readMindmapAiAttachment(await docxFile(await makeDocx()))
  assert.equal(result.text, '需求说明 & acceptance criteria\n\n')
  assert.equal(result.mediaType, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
})

test('损坏、空白和伪装为 DOCX 的 ZIP 有清楚错误', async () => {
  await assert.rejects(readMindmapAiAttachment(file('bad.docx', 'not a zip')), /DOCX 文件已损坏/u)
  await assert.rejects(readMindmapAiAttachment(await docxFile(new JSZip().file('hello.txt', 'hello'))), /不是有效的 DOCX/u)
  await assert.rejects(readMindmapAiAttachment(await docxFile(await makeDocx(''))), /未读取到可用文字/u)
})

test('DOCX 内部文件个数和解压后体积均有上限', async () => {
  const manyFiles = await makeDocx()
  for (let index = 0; index < 513; index += 1) manyFiles.file(`extra${index}.txt`, 'a')
  await assert.rejects(readMindmapAiAttachment(await docxFile(manyFiles)), /内部文件过多/u)
  const tooLarge = await makeDocx()
  tooLarge.file('large.bin', 'x'.repeat(16 * 1024 * 1024 + 1))
  await assert.rejects(readMindmapAiAttachment(await docxFile(tooLarge)), /解压后的内容过大/u)
})

test('DOCX 不信任 ZIP 声明大小，实际解压超过声明值即失败', async () => {
  const zip = await makeDocx('x'.repeat(50_000))
  const bytes = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
  const view = new DataView(bytes.buffer)
  for (let offset = 0; offset <= bytes.length - 46; offset += 1) {
    if (view.getUint32(offset, true) !== 0x02014b50) continue
    const length = view.getUint16(offset + 28, true)
    const name = new TextDecoder().decode(bytes.subarray(offset + 46, offset + 46 + length))
    if (name === 'word/document.xml') view.setUint32(offset + 24, 8, true)
  }
  await assert.rejects(readMindmapAiAttachment(file('forged.docx', bytes)), /安全限制|损坏/u)
})

test('DOCX 拒绝内部路径穿越', async () => {
  const zip = await makeDocx()
  zip.file('../outside.xml', 'outside')
  await assert.rejects(readMindmapAiAttachment(await docxFile(zip)), /无效的内部路径/u)
})
