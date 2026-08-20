import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const hyperlinkSource = await readFile(
  new URL('../../libs/simple-mind-map/src/utils/hyperlink.js', import.meta.url),
  'utf8',
)
const {
  getSafeMindMapHyperlink,
  normalizeMindMapHyperlink,
} = await import(`data:text/javascript;charset=utf-8,${encodeURIComponent(hyperlinkSource)}`)

test('脑图超链接允许标准网页地址和明确的相对路径', () => {
  assert.equal(normalizeMindMapHyperlink(' https://example.com/path '), 'https://example.com/path')
  assert.equal(normalizeMindMapHyperlink('http://example.com'), 'http://example.com/')
  assert.equal(normalizeMindMapHyperlink('/docs/start'), '/docs/start')
  assert.equal(normalizeMindMapHyperlink('./next'), './next')
  assert.equal(normalizeMindMapHyperlink('../parent'), '../parent')
  assert.equal(normalizeMindMapHyperlink('#section'), '#section')
})

test('脑图超链接支持格式有效的邮箱和电话动作', () => {
  assert.equal(normalizeMindMapHyperlink('mailto:user@example.com'), 'mailto:user@example.com')
  assert.equal(normalizeMindMapHyperlink('tel:+86 138-0000-0000'), 'tel:+86 138-0000-0000')
  assert.throws(() => normalizeMindMapHyperlink('mailto:not-an-email'), /邮箱链接格式不正确/)
  assert.throws(() => normalizeMindMapHyperlink('tel:open-app'), /电话链接格式不正确/)
})

test('脑图超链接拒绝脚本、本地、临时、带凭据和模糊链接', () => {
  for (const value of [
    'javascript:alert(1)',
    'data:text/html,hello',
    'file:///tmp/a',
    'blob:https://example.com/id',
    '//example.com/path',
  ]) {
    assert.throws(() => normalizeMindMapHyperlink(value), /链接/)
  }
  assert.throws(() => normalizeMindMapHyperlink('https://user:secret@example.com'), /账号或密码/)
  assert.throws(() => normalizeMindMapHyperlink('example.com'), /必须包含协议/)
  assert.throws(() => normalizeMindMapHyperlink(`https://example.com/${'a'.repeat(4096)}`), /不能超过 4096/)
  assert.throws(() => normalizeMindMapHyperlink('https://example.com/\nnext'), /控制字符/)
})

test('渲染容错接口把导入数据中的危险链接降级为不可点击', () => {
  assert.equal(getSafeMindMapHyperlink('javascript:alert(1)'), '')
  assert.equal(getSafeMindMapHyperlink('https://example.com'), 'https://example.com/')
})

test('链接渲染和 SVG 标题使用安全 DOM 契约', async () => {
  const libraryRoot = new URL('../../libs/simple-mind-map/src/', import.meta.url)
  const [nodeContents, svgUtils, exportPlugin, editor] = await Promise.all([
    readFile(new URL('core/render/node/nodeCreateContents.js', libraryRoot), 'utf8'),
    readFile(new URL('utils/svg.js', libraryRoot), 'utf8'),
    readFile(new URL('plugins/Export.js', libraryRoot), 'utf8'),
    readFile(new URL('../../components/MindMap/NodeHyperlink.vue', import.meta.url), 'utf8'),
  ])

  assert.match(nodeContents, /getSafeMindMapHyperlink\(hyperlink\)/)
  assert.match(nodeContents, /rel: 'noopener noreferrer'/)
  assert.equal(nodeContents.includes('SVG(`<title>${hyperlinkTitle}</title>`)'), false)
  assert.equal(nodeContents.includes('SVG(`<title>${attachmentName}</title>`)'), false)
  assert.match(svgUtils, /title\.textContent = String\(value\)/)
  assert.match(exportPlugin, /addSafeSvgTitle\(node, name, \{ prepend: true \}\)/)
  assert.match(editor, /normalizeMindMapHyperlink\(input\)/)
  assert.match(editor, /if \(!href\) \{[\s\S]*protocol\.value = 'https:\/\/'/)
})
