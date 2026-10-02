import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { babelParse } from '@vue/compiler-sfc'

const rendererRoot = new URL('../../libs/simple-mind-map/src/core/render/node/', import.meta.url)
const [contentsSource, stylesSource] = await Promise.all([
  readFile(new URL('nodeCreateContents.js', rendererRoot), 'utf8'),
  readFile(new URL('Style.js', rendererRoot), 'utf8'),
])
const contents = babelParse(contentsSource, { sourceType: 'module' }).program.body
const createTag = contents.find(node => node.type === 'FunctionDeclaration' && node.id.name === 'createTagNode')
const defaults = contents.find(node => node.declarations?.some(item => item.id.name === 'defaultTagStyle'))
const styleClass = babelParse(stylesSource, { sourceType: 'module' }).program.body
  .find(node => node.type === 'ClassDeclaration' && node.id.name === 'Style')
const styleMethods = styleClass.body.body.filter(node => ['tagText', 'tagRect'].includes(node.key.name))
const TagStyle = new Function(`return class { ${styleMethods.map(node => stylesSource.slice(node.start, node.end)).join('\n')} }`)()

// Execute production tag rendering; SVG primitives only record output and
// provide a fixed text measurement so dimensions remain deterministic in Node.
class SvgNode {
  constructor() { this.node = {}; this.children = []; this.attrs = {} }
  on() { return this }
  add(node) { this.children.push(node); return this }
  text(value) { this.node.textContent = value; return this }
  fill(value) { this.attrs.fill = value.color; return this }
  css(value) { Object.assign(this.attrs, value); return this }
  bbox() { return { width: 40, height: 18 } }
  size(width, height) { Object.assign(this.attrs, { width, height }); return this }
  radius(value) { this.attrs.radius = value; return this }
  x(value) { this.attrs.x = value; return this }
  cy(value) { this.attrs.cy = value; return this }
  load(value) { this.attrs.src = value; return this }
}
const bindings = {
  G: SvgNode, Text: SvgNode, Rect: SvgNode, SVGImage: SvgNode,
  SVG: markup => new SvgNode().load(markup),
  iconsSvg: { getNodeIconListIcon: key => key === 'priority_1' ? '<svg></svg>' : '' },
  addSafeSvgTitle: (node, text) => { node.attrs.title = text },
  generateColorByContent: () => '#fallback',
}
const createTagNode = new Function(...Object.keys(bindings), `
  ${contentsSource.slice(defaults.start, defaults.end)}
  ${contentsSource.slice(createTag.start, createTag.end)}
  return createTagNode
`)(...Object.values(bindings))

function render(tags) {
  return createTagNode.call({
    getData: () => tags,
    mindMap: { opt: { maxTag: 5 }, themeConfig: { iconSize: 18 }, emit() {} },
    style: new TagStyle(),
  })
}

test('AI and template tag references render all custom definition styles without copied node layout', () => {
  const tag = {
    tagId: 8,
    text: '待处理',
    style: {
      fill: '#123456', color: '#fafafa', fontSize: 18,
      radius: 9, paddingX: 15, placement: 'top', align: 'left',
    },
  }
  const original = structuredClone(tag)
  const [rendered] = render([tag])
  const [rect, text] = rendered.node.children
  assert.equal(rendered.placement, 'top')
  assert.equal(rendered.align, 'left')
  assert.equal(rendered.width, 70)
  assert.equal(rect.attrs.fill, '#123456')
  assert.equal(rect.attrs.radius, 9)
  assert.equal(text.attrs.fill, '#fafafa')
  assert.equal(text.attrs['font-size'], '18px')
  assert.equal(text.attrs.x, 15)
  assert.deepEqual(tag, original, 'rendering must not turn definition defaults into local overrides')
})

test('node-local tag layout continues to override custom definition defaults', () => {
  const [rendered] = render([{
    tagId: 8, text: '待处理', placement: 'left', align: 'bottom',
    style: { placement: 'top', align: 'right' },
  }])
  assert.equal(rendered.placement, 'left')
  assert.equal(rendered.align, 'bottom')
})

test('managed marker references also inherit their definition layout', () => {
  const [rendered] = render([{
    tagId: 9, text: '优先级 1',
    style: { iconKey: 'priority_1', placement: 'bottom', align: 'right' },
  }])
  assert.equal(rendered.placement, 'bottom')
  assert.equal(rendered.align, 'right')
  assert.equal(rendered.width, 18)
  assert.equal(rendered.node.children[0].attrs.src, '<svg></svg>')
  assert.equal(rendered.node.attrs.title, '优先级 1')
})

test('legacy string tags and tags without custom layout keep their default placement', () => {
  const rendered = render(['旧标签', { tagId: 8, text: '托管标签', style: { radius: 0, paddingX: 0 } }])
  for (const tag of rendered) {
    assert.equal(tag.placement, null)
    assert.equal(tag.align, null)
  }
  assert.equal(rendered[0].node.children[1].node.textContent, '旧标签')
  assert.equal(rendered[1].width, 40)
})
