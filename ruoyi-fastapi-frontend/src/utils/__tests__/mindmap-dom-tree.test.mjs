import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  applyStyleToDomTags,
  removeDomElements,
  replaceDomTextNodes,
  walkDomDescendants,
} from '../../libs/simple-mind-map/src/utils/domTree.js'

const ownerDocument = {
  createTextNode(value) {
    return createText(value)
  },
}

const attach = (parent, ...children) => {
  children.forEach(child => {
    child.parentNode = parent
    child.ownerDocument = ownerDocument
    parent.childNodes.push(child)
  })
  return parent
}

const createElement = (tagName, classNames = []) => ({
  nodeType: 1,
  tagName: tagName.toUpperCase(),
  style: { cssText: '' },
  classList: { contains: name => classNames.includes(name) },
  childNodes: [],
  parentNode: null,
  ownerDocument,
  replaceChild(next, previous) {
    const index = this.childNodes.indexOf(previous)
    if (index < 0) return
    next.parentNode = this
    next.ownerDocument = ownerDocument
    previous.parentNode = null
    this.childNodes.splice(index, 1, next)
  },
  removeChild(child) {
    const index = this.childNodes.indexOf(child)
    if (index < 0) return
    child.parentNode = null
    this.childNodes.splice(index, 1)
  },
})

const createText = value => ({
  nodeType: 3,
  nodeValue: value,
  childNodes: [],
  parentNode: null,
  ownerDocument,
})

test('DOM style application keeps stable order and stops below matched tags', () => {
  const nestedMatch = createElement('p')
  const firstMatch = attach(createElement('p'), nestedMatch)
  const secondMatch = createElement('p')
  const root = attach(createElement('div'), firstMatch, attach(createElement('span'), secondMatch))

  applyStyleToDomTags(root, ['p'], 'margin:0')
  assert.equal(firstMatch.style.cssText, 'margin:0')
  assert.equal(secondMatch.style.cssText, 'margin:0')
  assert.equal(nestedMatch.style.cssText, '')
})

test('DOM text replacement processes adjacent and deeply nested text snapshots', () => {
  const nested = attach(createElement('span'), createText('alpha alpha'))
  const root = attach(createElement('div'), createText('alpha'), createText('beta alpha'), nested)
  replaceDomTextNodes(root, value => value.replaceAll('alpha', 'x'))
  assert.deepEqual(root.childNodes.slice(0, 2).map(node => node.nodeValue), ['x', 'beta x'])
  assert.equal(nested.childNodes[0].nodeValue, 'x x')
})

test('DOM removal snapshots live child lists so adjacent formulas are not skipped', () => {
  const formulaA = createElement('span', ['ql-formula'])
  const formulaB = createElement('span', ['ql-formula'])
  const nestedFormula = createElement('span', ['ql-formula'])
  const normal = attach(createElement('span'), nestedFormula)
  const root = attach(createElement('div'), formulaA, formulaB, normal)

  removeDomElements(root, element => element.classList.contains('ql-formula'))
  assert.deepEqual(root.childNodes, [normal])
  assert.deepEqual(normal.childNodes, [])
})

test('DOM descendant traversal handles 20,000 levels without recursion', () => {
  const root = createElement('div')
  let current = root
  for (let depth = 0; depth < 20_000; depth += 1) {
    const child = createElement('span')
    attach(current, child)
    current = child
  }
  let count = 0
  walkDomDescendants(root, { onElement: () => { count += 1 } })
  assert.equal(count, 20_000)
})

test('rich-text DOM utilities no longer maintain local recursive walkers', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/utils/index.js', import.meta.url),
    'utf8'
  )
  assert.match(source, /applyStyleToDomTags\(addHtmlStyleEl, tag, style\)/)
  assert.match(source, /replaceDomTextNodes\(replaceHtmlTextEl/)
  assert.match(source, /removeDomElements\(node, element =>/)
  assert.doesNotMatch(source, /let walk = root =>/)
  assert.doesNotMatch(source, /const walk = root =>/)
})
