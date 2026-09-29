import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../../views/mindmap/edit.vue', import.meta.url), 'utf8')

test('编辑页在挂载和卸载时成对启用、解除根节点横向导航保护', () => {
  const mounted = source.match(/onMounted\(\(\) => \{([\s\S]*?)\n\}\)/)?.[1] || ''
  const unmounted = source.match(/onBeforeUnmount\(\(\) => \{([\s\S]*?)\n\}\)/)?.[1] || ''
  for (const target of ['documentElement', 'body']) {
    assert.ok(mounted.includes(`document.${target}.classList.add(MINDMAP_DETAIL_PAGE_BODY_CLASS)`))
    assert.ok(unmounted.includes(`document.${target}.classList.remove(MINDMAP_DETAIL_PAGE_BODY_CLASS)`))
  }
})

test('根视口和编辑页只禁止横向越界，保留纵向滚动和普通导航', () => {
  const globalStyle = source.match(/<style lang="scss">([\s\S]*?)<\/style>/)?.[1] || ''
  const scopedStyle = source.match(/<style scoped lang="scss">([\s\S]*?)<\/style>/)?.[1] || ''
  assert.match(globalStyle, /html\.mindmap-detail-page-active,\s*body\.mindmap-detail-page-active\s*\{\s*overscroll-behavior-x:\s*none;/)
  assert.match(scopedStyle, /\.mindmap-edit-page\s*\{[^}]*overscroll-behavior-x:\s*none;/)
  assert.doesNotMatch(source, /overscroll-behavior(?:-y)?:\s*(?:none|contain)/)
  assert.doesNotMatch(source, /history\.(?:pushState|replaceState|go)|addEventListener\(['"]popstate/)
  assert.match(source, /@click="goBack"/)
  assert.match(source, /onBeforeRouteLeave\(confirmEditorNavigation\)/)
})

test('画布仍同步阻止原生滚轮行为并将事件交给既有平移缩放处理', () => {
  const eventSource = readFileSync(new URL('../../libs/simple-mind-map/src/core/event/Event.js', import.meta.url), 'utf8')
  const editorSource = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')
  assert.match(eventSource, /addEventListener\('wheel', this\.onMousewheel, \{ passive: false \}\)/)
  assert.match(eventSource, /_throttleWheelRAF\(fn\)\s*\{[\s\S]*?e\.preventDefault\(\)[\s\S]*?requestAnimationFrame/)
  assert.match(editorSource, /customHandleMousewheel:[\s\S]*?shouldZoomMindmapWheel\(e, mm\.opt\)/)
  assert.match(editorSource, /mm\.view\.translateXY\(\s*dampen\(-e\.deltaX \* translateRatio\)/)
})
