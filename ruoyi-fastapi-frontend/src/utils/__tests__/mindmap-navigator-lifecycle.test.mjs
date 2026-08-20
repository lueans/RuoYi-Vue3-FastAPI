import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const navigatorSourceUrl = new URL('../../components/MindMap/Navigator.vue', import.meta.url)

test('小地图截图只允许当前打开实例的异步结果回写', async () => {
  const source = await readFile(navigatorSourceUrl, 'utf8')

  assert.match(source, /createScopedAsyncSession/)
  assert.match(source, /const activeMindMap = props\.mindMap/)
  assert.match(source, /const session = miniMapSession\.activate\(activeMindMap\)/)
  assert.match(source, /props\.mindMap !== activeMindMap/)
  assert.match(source, /!miniMapSession\.isCurrent\(session\)/)
  assert.match(source, /await result\.getImgUrl/)
  assert.match(source, /catch \{[\s\S]*miniMapSession\.isCurrent\(session\)/)
})

test('关闭、换图和卸载会释放小地图图片及拖拽状态', async () => {
  const source = await readFile(navigatorSourceUrl, 'utf8')

  assert.match(source, /function invalidateMiniMap\(\{ clearImage = false \} = \{\}\)/)
  assert.match(source, /miniMapSession\.invalidate\(\)[\s\S]*mindMapImg\.value = ''/)
  assert.match(source, /if \(!nextShow\) \{[\s\S]*releaseMiniMapDrag\(\)[\s\S]*clearImage: true/)
  assert.match(source, /watch\(\(\) => props\.mindMap,[\s\S]*releaseMiniMapDrag\(oldMm\)[\s\S]*clearImage: true[\s\S]*immediate: true/)
  assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*componentAlive = false[\s\S]*releaseMiniMapDrag\(\)[\s\S]*clearImage: true/)
})

test('小地图暴露区域名称且缩略图保持装饰性', async () => {
  const source = await readFile(navigatorSourceUrl, 'utf8')

  assert.match(source, /role="region"/)
  assert.match(source, /aria-label="脑图小地图"/)
  assert.match(source, /<img :src="mindMapImg" alt="" draggable="false"/)
  assert.match(source, /Math\.max\(0, Math\.min\(window\.innerWidth - 80, 370\)\)/)
})
