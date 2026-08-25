import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const viewUrl = new URL('../../views/mindmap/view.vue', import.meta.url)
const apiUrl = new URL('../../api/mindmap/share.js', import.meta.url)

test('公开分享详情请求编码路径令牌并支持取消', async () => {
  const source = await readFile(apiUrl, 'utf8')
  const viewBlock = source.match(/export function viewByShareToken[\s\S]*?\n\}/)?.[0] || ''

  assert.match(viewBlock, /viewByShareToken\(shareToken, \{ signal \} = \{\}\)/)
  assert.match(viewBlock, /encodeURIComponent\(String\(shareToken\)\)/)
  assert.match(viewBlock, /headers: \{ isToken: false \}/)
  assert.match(viewBlock, /signal,/)
})

test('公开分享预览隔离路由切换、插件加载和实例构造的迟到任务', async () => {
  const source = await readFile(viewUrl, 'utf8')
  const loadBlock = source.match(/async function loadShare[\s\S]*?\n\}/)?.[0] || ''
  const currentBlock = source.match(/function isShareSessionCurrent[\s\S]*?\n\}/)?.[0] || ''
  const cancelBlock = source.match(/function cancelShareLoad[\s\S]*?\n\}/)?.[0] || ''
  const initBlock = source.match(/function initMindMap[\s\S]*?\n\}/)?.[0] || ''
  const unmountBlock = source.match(/onBeforeUnmount\(\(\) => \{[\s\S]*?\n\}\)/)?.[0] || ''

  assert.match(source, /createScopedAsyncSession/)
  assert.match(currentBlock, /componentActive/)
  assert.match(currentBlock, /shareSession\.isCurrent\(session\)/)
  assert.match(currentBlock, /getRouteShareToken\(\) === session\?\.identity/)
  assert.match(currentBlock, /signal\?\.aborted !== true/)
  assert.match(cancelBlock, /shareSession\.invalidate\(\)/)
  assert.match(cancelBlock, /shareRequestController\?\.abort\(\)/)

  assert.ok(loadBlock.indexOf('cancelShareLoad()') < loadBlock.indexOf('shareSession.activate(token)'))
  assert.match(loadBlock, /viewByShareToken\(token, \{ signal \}\)/)
  assert.match(loadBlock, /const data = res\.data[\s\S]*?registerPreviewPlugins/)
  assert.match(loadBlock, /documentData: data\.documentData/)
  assert.ok((loadBlock.match(/isShareSessionCurrent\(session, signal\)/g) || []).length >= 5)
  assert.match(loadBlock, /await nextTick\(\)[\s\S]*?isShareSessionCurrent\(session, signal\)/)
  assert.match(loadBlock, /catch \(e\) \{\s*if \(!isShareSessionCurrent\(session, signal\)\) return false/)
  assert.match(loadBlock, /finally \{[\s\S]*?if \(isShareSessionCurrent\(session, signal\)\) loading\.value = false/)

  assert.match(initBlock, /const instance = new MindMap/)
  assert.match(initBlock, /if \(!isShareSessionCurrent\(session, signal\)\) \{\s*instance\.destroy\(\)/)
  assert.match(initBlock, /mindMap\.value = instance/)
  assert.match(unmountBlock, /componentActive = false[\s\S]*?cancelShareLoad\(\)[\s\S]*?destroyMindMap\(\)/)
  assert.match(source, /function handleShortcut\(event\) \{\s*if \(!mindMap\.value\) return/)
  assert.match(source, /role="region"[\s\S]*?:aria-label="`\$\{mindmapData\.name \|\| '脑图'\}只读画布`"[\s\S]*?tabindex="0"/)
})
