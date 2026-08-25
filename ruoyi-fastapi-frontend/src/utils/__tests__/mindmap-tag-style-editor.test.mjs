import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sourceUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)

test('点击节点标签打开标签侧边栏且不再挂载旧标签弹窗', async () => {
  const source = await readFile(sourceUrl, 'utf8')
  const handler = source.slice(
    source.indexOf('function onNodeTagClick'),
    source.indexOf('function bindBusEvents')
  )

  assert.match(source, /'node_tag_click'/)
  assert.match(source, /bus\.on\('node_tag_click', onNodeTagClick\)/)
  assert.match(source, /bus\.off\('node_tag_click', onNodeTagClick\)/)
  assert.match(handler, /sourceMindMap !== activeMindMap/)
  assert.match(handler, /node\.mindMap !== activeMindMap/)
  assert.match(handler, /onOpenSidebar\('nodeTagSidebar'\)/)
  assert.doesNotMatch(source, /<NodeTagStyle/)
  assert.doesNotMatch(source, /import NodeTagStyle/)
})
