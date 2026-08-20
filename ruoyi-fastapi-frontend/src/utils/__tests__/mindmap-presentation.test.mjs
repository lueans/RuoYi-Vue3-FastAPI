import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)
const libraryRoot = new URL('../../libs/simple-mind-map/src/', import.meta.url)
const appFullscreenSource = await readFile(new URL('utils/index.js', componentRoot), 'utf8')

test('全屏兼容层优先使用标准 API 并将成功、拒绝和退出统一为 Promise', async () => {
  const previousDocument = globalThis.document
  const fakeDocument = {
    onfullscreenchange: null,
    documentElement: {},
    fullscreenElement: null,
    exitFullscreen() {
      this.fullscreenElement = null
    },
  }
  globalThis.document = fakeDocument
  try {
    const moduleUrl = `data:text/javascript;base64,${Buffer.from(appFullscreenSource).toString('base64')}`
    const {
      exitFullScreen,
      fullScreen,
      fullscrrenEvent,
      getFullscreenElement,
      requestFullscreenAndWait,
    } = await import(moduleUrl)
    let requested = false
    const element = {
      requestFullscreen() {
        requested = true
        fakeDocument.fullscreenElement = element
      },
    }

    await fullScreen(element)
    assert.equal(requested, true)
    assert.equal(getFullscreenElement(), element)
    assert.equal(await requestFullscreenAndWait(element, 5), true)
    assert.equal(fullscrrenEvent, 'onfullscreenchange')
    await exitFullScreen()
    assert.equal(getFullscreenElement(), null)
    await assert.rejects(fullScreen({}), /不支持全屏模式/)
  } finally {
    globalThis.document = previousDocument
  }
})

test('全屏控件同步画布和编辑页状态，并允许再次点击退出', async () => {
  const source = await readFile(new URL('Fullscreen.vue', componentRoot), 'utf8')

  assert.match(source, /:aria-pressed="isCanvasFullscreen"/)
  assert.match(source, /:aria-pressed="isPageFullscreen"/)
  assert.match(source, /closest\?\.\('\.mindmap-edit-page'\)/)
  assert.match(source, /await exitFullscreenAndWait\(\)/)
  assert.match(source, /await requestFullscreenAndWait\(target\)/)
  assert.match(source, /fullscreenElement\.value = getFullscreenElement\(\)/)
  assert.match(source, /ElMessage\.warning/)
})

test('演示模式只在全屏成功后开放控制，并完整恢复事件、数据和焦点', async () => {
  const [component, plugin, editor] = await Promise.all([
    readFile(new URL('Demonstrate.vue', componentRoot), 'utf8'),
    readFile(new URL('plugins/Demonstrate.js', libraryRoot), 'utf8'),
    readFile(new URL('Edit.vue', componentRoot), 'utf8'),
  ])

  assert.match(component, /bus\.on\('enter_demonstrate', onEnterDemonstrate\)/)
  assert.match(component, /exitDemonstrateBtnRef\.value\?\.focus\(\)/)
  assert.match(component, /enterDemonstrateBtnRef\.value\?\.focus\(\)/)
  assert.match(component, /role="toolbar"/)
  assert.match(component, /type="number"/)
  assert.match(plugin, /if \(this\.isInDemonstrate \|\| this\.isEntering\)/)
  assert.match(plugin, /this\.mindMap\.emit\('enter_demonstrate'\)/)
  assert.match(plugin, /if \(this\.renderTree\) this\.mindMap\.updateData/)
  assert.match(plugin, /this\.enterRenderEndHandler/)
  assert.match(plugin, /requestFullscreenAndWait\(this\.mindMap\.el\)/)
  assert.match(plugin, /left !== undefined/)
  assert.match(editor, /'enter_demonstrate'/)
})

test('演示进入绑定组件和插件生命周期并拒绝退出后的迟到回调', async () => {
  const [component, plugin] = await Promise.all([
    readFile(new URL('Demonstrate.vue', componentRoot), 'utf8'),
    readFile(new URL('plugins/Demonstrate.js', libraryRoot), 'utf8'),
  ])

  assert.match(component, /const requestId = \+\+enterRequestId/)
  assert.match(component, /isCurrentEnterRequest\(requestId, mindMap\)/)
  assert.match(component, /componentAlive = false[\s\S]*enterRequestId\+\+/)
  assert.match(component, /isEnterDemonstrate\.value \|\| isEntering\.value/)
  assert.match(plugin, /const requestId = \+\+this\.enterRequestId/)
  assert.match(plugin, /if \(!this\.isEnterRequestCurrent\(requestId\)\)/)
  assert.match(plugin, /this\.releaseOwnedFullscreen\(\)/)
  assert.equal((plugin.match(/this\.isDestroyed = true\s+this\.exit\(\)/g) || []).length, 2)
  assert.match(plugin, /jump\(index\) \{[\s\S]*!this\.isInDemonstrate/)
  assert.match(plugin, /expandToNodeUid\(uid, \(\) => \{\s*if \(!this\.isInDemonstrate\) return/)
  assert.match(plugin, /this\.mindMap\.render\(\(\) => \{\s*if \(!this\.isInDemonstrate\) return/)
})

test('鼠标操作切换使用可聚焦按钮并暴露当前模式', async () => {
  const source = await readFile(new URL('MouseAction.vue', componentRoot), 'utf8')

  assert.equal(/<div[^>]*class="btn iconfont"[^>]*@click="toggleAction"/.test(source), false)
  assert.match(source, /<button[\s\S]*type="button"[\s\S]*:aria-label="actionLabel"/)
  assert.match(source, /:aria-pressed="useLeftKeySelectionRightKeyDrag"/)
  assert.match(source, /&:focus-visible/)
})
