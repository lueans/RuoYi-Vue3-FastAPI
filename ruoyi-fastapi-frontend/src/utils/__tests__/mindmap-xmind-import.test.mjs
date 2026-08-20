import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const parserUrl = new URL('../../libs/simple-mind-map/src/parse/xmindImport.js', import.meta.url)
const parserSource = await readFile(parserUrl, 'utf8')
const parser = await import(`data:text/javascript;base64,${Buffer.from(parserSource).toString('base64')}`)

function element(name, attributes = {}, childNodes = []) {
  return {
    nodeType: 1,
    nodeName: name,
    attributes: Object.entries(attributes).map(([attributeName, value]) => ({
      name: attributeName,
      value,
    })),
    childNodes,
  }
}

function textNode(value, nodeType = 3) {
  return { nodeType, nodeValue: value }
}

test('legacy XMind XML is converted to the existing simple-mind-map element shape', () => {
  const root = element('xmap-content', { xmlns: 'urn:xmind' }, [
    textNode('\n  '),
    element('topic', { id: 'root', 'xlink:href': 'https://example.com' }, [
      element('title', {}, [textNode('Root from CDATA', 4)]),
    ]),
  ])
  class FakeDOMParser {
    parseFromString(xml, mimeType) {
      assert.equal(xml, '<xmap-content />')
      assert.equal(mimeType, 'application/xml')
      return {
        documentElement: root,
        getElementsByTagName: () => [],
      }
    }
  }

  const result = parser.parseXmindXml('<xmap-content />', { DOMParserImpl: FakeDOMParser })
  const topic = result.elements[0].elements[0]

  assert.equal(result.elements[0].name, 'xmap-content')
  assert.equal(result.elements[0].attributes.xmlns, 'urn:xmind')
  assert.equal(topic.attributes['xlink:href'], 'https://example.com')
  assert.deepEqual(topic.elements[0].elements[0], {
    type: 'text',
    text: 'Root from CDATA',
  })
})

test('legacy XML rejects DTD, entity declarations and parser errors', () => {
  class ErrorDOMParser {
    parseFromString() {
      return {
        documentElement: element('parsererror'),
        getElementsByTagName: () => [element('parsererror')],
      }
    }
  }

  assert.throws(
    () => parser.parseXmindXml('<!DOCTYPE x [<!ENTITY a "x">]><x/>', { DOMParserImpl: ErrorDOMParser }),
    /不允许 DTD 或实体声明/
  )
  assert.throws(
    () => parser.parseXmindXml('<broken>', { DOMParserImpl: ErrorDOMParser }),
    /格式无效/
  )
})

test('XMind archive limits decompressed entry count, item size and total size', () => {
  const entry = (name, size) => ({ name, dir: false, _data: { uncompressedSize: size } })

  assert.equal(parser.validateXmindArchive({ content: entry('content.json', 1024) }), true)
  assert.throws(
    () => parser.validateXmindArchive({ huge: entry('huge.bin', parser.MAX_XMIND_DOCUMENT_SIZE + 1) }),
    /解压后过大/
  )
  const manyEntries = Object.fromEntries(Array.from(
    { length: parser.MAX_XMIND_ARCHIVE_ENTRIES + 1 },
    (_, index) => [index, entry(`${index}.bin`, 1)]
  ))
  assert.throws(() => parser.validateXmindArchive(manyEntries), /文件数量异常/)
  const largeEntries = Object.fromEntries(Array.from(
    { length: 6 },
    (_, index) => [index, entry(`${index}.bin`, 18 * 1024 * 1024)]
  ))
  assert.throws(() => parser.validateXmindArchive(largeEntries), /总体积不能超过 100MB/)
})

test('XMind browser entry no longer imports xml-js or a Node stream polyfill', async () => {
  const [xmindSource, packageSource, lockSource, vendoredPackageSource] = await Promise.all([
    readFile(new URL('../../libs/simple-mind-map/src/parse/xmind.js', import.meta.url), 'utf8'),
    readFile(new URL('../../../package.json', import.meta.url), 'utf8'),
    readFile(new URL('../../../package-lock.json', import.meta.url), 'utf8'),
    readFile(new URL('../../libs/simple-mind-map/package.json', import.meta.url), 'utf8'),
  ])

  assert.doesNotMatch(xmindSource, /from ['"]xml-js['"]/)
  assert.match(xmindSource, /parseXmindXml\(xml\)/)
  assert.equal(Object.hasOwn(JSON.parse(packageSource).dependencies, 'xml-js'), false)
  assert.equal(Object.hasOwn(JSON.parse(lockSource).packages, 'node_modules/xml-js'), false)
  assert.equal(JSON.parse(vendoredPackageSource).type, 'module')
})
