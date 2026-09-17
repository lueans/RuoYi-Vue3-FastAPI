import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const richTextSourceUrl = new URL(
  '../../libs/simple-mind-map/src/plugins/RichText.js',
  import.meta.url,
)

function extractMethod(source, signature) {
  const start = source.indexOf(`  ${signature} {`)
  assert.ok(start >= 0, `missing RichText method: ${signature}`)
  const openBrace = source.indexOf('{', start)
  let depth = 0
  for (let index = openBrace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1
    if (source[index] === '}') {
      depth -= 1
      if (depth === 0) {
        return {
          args: signature.slice(signature.indexOf('(') + 1, signature.lastIndexOf(')')),
          body: source.slice(openBrace + 1, index),
        }
      }
    }
  }
  assert.fail(`unterminated RichText method: ${signature}`)
}

function compileMethod(source, signature, dependencies = {}) {
  const { args, body } = extractMethod(source, signature)
  const names = Object.keys(dependencies)
  return Function(
    ...names,
    `'use strict'; return function (${args}) {${body}}`,
  )(...names.map(name => dependencies[name]))
}

function walk(node, parent, visitor) {
  if (!node) return
  visitor(node, parent)
  for (const child of node.children || []) walk(child, node, visitor)
}

function compareVersion(left, right) {
  const leftParts = String(left).split('.').map(Number)
  const rightParts = String(right).split('.').map(Number)
  const length = Math.max(leftParts.length, rightParts.length)
  for (let index = 0; index < length; index += 1) {
    const difference = (leftParts[index] || 0) - (rightParts[index] || 0)
    if (difference < 0) return '<'
    if (difference > 0) return '>'
  }
  return '='
}

const htmlEscape = value => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;')

async function createConversionMethods() {
  const source = await readFile(richTextSourceUrl, 'utf8')
  const handleDataToRichText = compileMethod(
    source,
    'handleDataToRichText(data)',
    {
      htmlEscape,
      isUndef: value => value === undefined || value === null,
    },
  )
  const handleSetData = compileMethod(source, 'handleSetData(data)', {
    compareVersion,
    formatGetNodeGeneralization: data => data.generalization || [],
    walk,
  })
  return { handleDataToRichText, handleSetData }
}

test('缺少 smmVersion 的已转换富文本保持幂等', async () => {
  const methods = await createConversionMethods()
  const document = {
    data: {
      richText: true,
      text: '<p><span>用户登录功能</span></p>',
      generalization: [{
        richText: true,
        text: '<p><strong>概要</strong></p>',
      }],
    },
    children: [{
      data: {
        richText: true,
        text: '<p><em>子节点</em></p>',
      },
      children: [],
    }],
  }
  const original = structuredClone(document)
  const context = { handleDataToRichText: methods.handleDataToRichText }

  methods.handleSetData.call(context, document)
  methods.handleSetData.call(context, document)

  assert.deepEqual(document, original)
  assert.equal(document.data.resetRichText, undefined)
  assert.equal(document.data.generalization[0].resetRichText, undefined)
})

test('缺少 smmVersion 的普通文本只转换一次并正确转义', async () => {
  const methods = await createConversionMethods()
  const document = {
    data: {
      richText: false,
      text: '<用户登录 & 权限 "检查">',
    },
    children: [],
  }
  const context = { handleDataToRichText: methods.handleDataToRichText }

  methods.handleSetData.call(context, document)

  assert.equal(document.data.richText, true)
  assert.equal(
    document.data.text,
    '&lt;用户登录 &amp; 权限 &quot;检查&quot;&gt;',
  )
  assert.equal(document.data.resetRichText, true)

  delete document.data.resetRichText
  const converted = structuredClone(document)
  methods.handleSetData.call(context, document)

  assert.deepEqual(document, converted)
})

test('带明确旧版本的富文本仍保留 legacy reset 兼容行为', async () => {
  const methods = await createConversionMethods()
  const document = {
    smmVersion: '0.12.0',
    data: {
      richText: true,
      text: '<p>旧版富文本</p>',
    },
    children: [],
  }
  const context = { handleDataToRichText: methods.handleDataToRichText }

  methods.handleSetData.call(context, document)

  assert.equal(document.data.text, '<p>旧版富文本</p>')
  assert.equal(document.data.resetRichText, true)
})
