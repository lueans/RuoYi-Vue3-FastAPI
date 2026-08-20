import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const libraryRoot = new URL('../../libs/simple-mind-map/src/', import.meta.url)
const hyperlinkSource = await readFile(new URL('utils/hyperlink.js', libraryRoot), 'utf8')
const hyperlinkModuleUrl = `data:text/javascript;base64,${Buffer.from(hyperlinkSource).toString('base64')}`
const attachmentSource = (
  await readFile(new URL('utils/attachment.js', libraryRoot), 'utf8')
).replace("from './hyperlink'", `from '${hyperlinkModuleUrl}'`)
const {
  getSafeMindMapAttachmentUrl,
  inferMindMapAttachmentName,
  normalizeMindMapAttachmentUrl,
} = await import(`data:text/javascript;base64,${Buffer.from(attachmentSource).toString('base64')}`)

test('附件允许网页地址、同源相对路径和受控兼容 Data URL', () => {
  assert.equal(normalizeMindMapAttachmentUrl('https://example.com/a.pdf'), 'https://example.com/a.pdf')
  assert.equal(normalizeMindMapAttachmentUrl('/files/a.pdf'), '/files/a.pdf')
  assert.equal(
    normalizeMindMapAttachmentUrl('data:application/pdf;base64,AA=='),
    'data:application/pdf;base64,AA==',
  )
  assert.equal(
    normalizeMindMapAttachmentUrl('data:text/plain;charset=utf-8,hello'),
    'data:text/plain;charset=utf-8,hello',
  )
})

test('附件拒绝危险协议、动作链接、可执行 Data 类型和超大内联内容', () => {
  for (const value of [
    'javascript:alert(1)',
    'file:///tmp/a.pdf',
    'blob:https://example.com/id',
    'mailto:user@example.com',
    'tel:+8613800000000',
    'data:text/html,<script>alert(1)</script>',
    'data:image/svg+xml,<svg></svg>',
  ]) {
    assert.throws(() => normalizeMindMapAttachmentUrl(value), /附件|链接/)
  }
  assert.throws(
    () => normalizeMindMapAttachmentUrl('data:application/pdf;base64,AAAA', { maxDataUrlLength: 10 }),
    /不能超过 10 MB/,
  )
})

test('附件容错和名称推导适用于导入及旧数据', () => {
  assert.equal(getSafeMindMapAttachmentUrl('javascript:alert(1)'), '')
  assert.equal(getSafeMindMapAttachmentUrl('https://example.com/a.pdf'), 'https://example.com/a.pdf')
  assert.equal(inferMindMapAttachmentName('https://example.com/files/report%202026.pdf'), 'report 2026.pdf')
  assert.equal(inferMindMapAttachmentName('/'), '附件')
  assert.equal(inferMindMapAttachmentName('data:application/pdf;base64,AA=='), '附件')
})

test('附件工具栏、编辑器事件和渲染层形成完整功能链路', async () => {
  const componentRoot = new URL('../../components/MindMap/', import.meta.url)
  const [toolbar, editor, attachmentEditor, nodeContents] = await Promise.all([
    readFile(new URL('Toolbar.vue', componentRoot), 'utf8'),
    readFile(new URL('Edit.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeAttachment.vue', componentRoot), 'utf8'),
    readFile(new URL('core/render/node/nodeCreateContents.js', libraryRoot), 'utf8'),
  ])

  assert.match(toolbar, /attachment: \{ icon: 'iconfujian', event: 'showNodeAttachment' \}/)
  assert.match(editor, /<NodeAttachment v-if="mindMap" :readonly="isReadonly"/)
  assert.match(attachmentEditor, /bus\.on\('node_attachmentClick', openAttachment\)/)
  assert.match(attachmentEditor, /bus\.on\('node_attachmentContextmenu', editAttachmentFromContextMenu\)/)
  assert.match(attachmentEditor, /anchor\.rel = 'noopener noreferrer'/)
  assert.match(attachmentEditor, /node\.setAttachment\(url, name\)/)
  assert.match(nodeContents, /getSafeMindMapAttachmentUrl\(attachmentUrl\)/)
})
