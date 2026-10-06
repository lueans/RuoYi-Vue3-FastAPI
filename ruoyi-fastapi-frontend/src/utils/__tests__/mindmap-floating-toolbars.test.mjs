import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('图片位置浮动工具条使用可聚焦控件和显式状态', async () => {
  const imageSource = await readFile(new URL('../../components/MindMap/NodeImgPlacementToolbar.vue', import.meta.url), 'utf8')

  assert.match(imageSource, /role="toolbar"[\s\S]*aria-label="节点图片位置"/)
  assert.match(imageSource, /:aria-pressed="currentPlacement === item\.value"/)
  assert.doesNotMatch(imageSource, /class="btn iconfont icontupianweizhi"/)
})
