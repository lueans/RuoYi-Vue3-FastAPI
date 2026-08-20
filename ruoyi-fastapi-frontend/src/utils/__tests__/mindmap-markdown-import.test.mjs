import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MARKDOWN_MULTI_ROOT_TEXT,
  getMarkdownNodeText,
  transformMarkdownAstToMindmap,
  transformMarkdownTo,
} from '../../libs/simple-mind-map/src/parse/markdownTo.js'
import {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_TREE_DEPTH,
} from '../../libs/simple-mind-map/src/utils/documentLimits.js'

const text = value => ({ type: 'text', value })
const paragraph = value => ({ type: 'paragraph', children: [text(value)] })
const listItem = (value, nested) => ({
  type: 'listItem',
  children: [
    paragraph(value),
    ...(nested ? [{ type: 'list', children: nested }] : []),
  ],
})

test('Markdown headings preserve hierarchy, skipped levels and inline text order', () => {
  assert.deepEqual(transformMarkdownTo([
    '# Root **bold** `code`',
    '### Deep child',
    '## Sibling child',
  ].join('\n\n')), {
    data: { text: 'Root bold code' },
    children: [
      { data: { text: 'Deep child' }, children: [] },
      { data: { text: 'Sibling child' }, children: [] },
    ],
  })
})

test('Markdown nested lists preserve every item and stable source order', () => {
  const root = transformMarkdownTo([
    '# Root',
    '- A',
    '  - A1',
    '  - A2',
    '- B',
  ].join('\n'))
  assert.deepEqual(root.children, [
    {
      data: { text: 'A' },
      children: [
        { data: { text: 'A1' }, children: [] },
        { data: { text: 'A2' }, children: [] },
      ],
    },
    { data: { text: 'B' }, children: [] },
  ])
})

test('Markdown multiple top-level headings and list items are retained under one explicit root', () => {
  const headings = transformMarkdownTo('# A\n\n# B')
  assert.equal(headings.data.text, MARKDOWN_MULTI_ROOT_TEXT)
  assert.deepEqual(headings.children.map(node => node.data.text), ['A', 'B'])

  const list = transformMarkdownTo('- A\n- B')
  assert.equal(list.data.text, MARKDOWN_MULTI_ROOT_TEXT)
  assert.deepEqual(list.children.map(node => node.data.text), ['A', 'B'])
})

test('Markdown notes and plain documents are retained instead of silently discarded', () => {
  const root = transformMarkdownTo([
    '# Root',
    '',
    '**root note** with `code`',
    '',
    '## Child',
    '',
    'child note',
  ].join('\n'))
  assert.equal(root.data.note, '**root note** with `code`')
  assert.equal(root.children[0].data.note, 'child note')

  const plain = transformMarkdownTo('Plain title\n\nMore details')
  assert.equal(plain.data.text, 'Plain title')
  assert.equal(plain.data.note, 'More details')
})

test('Markdown list item continuation blocks become notes while nested lists remain children', () => {
  const tree = {
    type: 'root',
    children: [{
      type: 'list',
      children: [{
        type: 'listItem',
        children: [
          paragraph('Item'),
          paragraph('Item note'),
          { type: 'list', children: [listItem('Child')] },
        ],
      }],
    }],
  }
  const root = transformMarkdownAstToMindmap(tree)
  assert.equal(root.data.text, 'Item')
  assert.equal(root.data.note, 'Item note')
  assert.equal(root.children[0].data.text, 'Child')
})

test('Markdown conversion enforces node limits while constructing the target tree', () => {
  const items = Array.from(
    { length: MAX_MINDMAP_NODE_COUNT - 1 },
    (_, index) => listItem(String(index))
  )
  const tree = {
    type: 'root',
    children: [
      { type: 'heading', depth: 1, children: [text('Root')] },
      { type: 'list', children: items },
    ],
  }
  assert.doesNotThrow(() => transformMarkdownAstToMindmap(tree))
  items.push(listItem('overflow'))
  assert.throws(
    () => transformMarkdownAstToMindmap(tree),
    /节点数量不能超过 20000/
  )
})

test('Markdown conversion handles a 256-level list iteratively and rejects level 257', () => {
  const createListChain = length => {
    let items = [listItem(String(length))]
    for (let depth = length - 1; depth >= 1; depth -= 1) {
      items = [listItem(String(depth), items)]
    }
    return { type: 'root', children: [{ type: 'list', children: items }] }
  }
  let current = transformMarkdownAstToMindmap(createListChain(MAX_MINDMAP_TREE_DEPTH))
  let depth = 1
  while (current.children.length > 0) {
    current = current.children[0]
    depth += 1
  }
  assert.equal(depth, MAX_MINDMAP_TREE_DEPTH)
  assert.throws(
    () => transformMarkdownAstToMindmap(createListChain(MAX_MINDMAP_TREE_DEPTH + 1)),
    /脑图层级不能超过 256/
  )
})

test('Markdown inline text extraction handles 20,000 nested containers without recursion', () => {
  let node = text('deep')
  for (let depth = 0; depth < 20_000; depth += 1) {
    node = { type: 'emphasis', children: [node] }
  }
  assert.equal(getMarkdownNodeText(node), 'deep')
})
