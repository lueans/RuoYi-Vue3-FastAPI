import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)

test('关闭主题覆盖确认不会提前改变选中态或暗色状态', async () => {
  const source = await readFile(new URL('Theme.vue', componentRoot), 'utf8')
  const useThemeSource = source.slice(source.indexOf('async function useTheme'), source.indexOf('function changeTheme'))
  const changeThemeSource = source.slice(source.indexOf('function changeTheme'), source.indexOf('function bindMindMap'))

  assert.match(useThemeSource, /themeChangePending\.value = true/)
  assert.match(useThemeSource, /await ElMessageBox\.confirm/)
  assert.match(useThemeSource, /if \(action !== 'cancel'\) return/)
  assert.doesNotMatch(useThemeSource, /currentTheme\.value = theme\.value/)
  assert.match(changeThemeSource, /currentTheme\.value = theme\.value[\s\S]*handleDark\(\)/)
  assert.match(source, /watch\(\(\) => props\.mindMap, bindMindMap, \{ immediate: true \}\)/)
})

test('主题和结构卡片使用具名原生选择按钮', async () => {
  const [theme, structure] = await Promise.all([
    readFile(new URL('Theme.vue', componentRoot), 'utf8'),
    readFile(new URL('Structure.vue', componentRoot), 'utf8'),
  ])

  assert.match(theme, /<button[\s\S]*class="themeItem"[\s\S]*:aria-pressed="item\.value === currentTheme"/)
  assert.match(theme, /:disabled="themeChangePending \|\| isReadonly"/)
  assert.doesNotMatch(theme, /<div\s+class="themeItem"/)
  assert.match(structure, /<summary ref="layoutSummaryRef" class="currentLayoutCard">[\s\S]*currentLayoutName[\s\S]*当前布局/)
  assert.match(structure, /<button[\s\S]*class="layoutItem"[\s\S]*:aria-label="`使用结构：/)
  assert.match(structure, /item !== currentLayout\.value/)
  assert.match(structure, /layoutNameMap/)
  assert.doesNotMatch(structure, /<div\s+class="layoutItem"/)
})

test('快捷颜色使用足够尺寸的具名按钮并公开选中状态', async () => {
  const source = await readFile(new URL('Color.vue', componentRoot), 'utf8')

  assert.match(source, /<button[\s\S]*class="colorItem iconfont"[\s\S]*:aria-pressed="isSelected\(item\)"/)
  assert.match(source, /aria-label="选择自定义颜色"/)
  assert.match(source, /width: 28px;[\s\S]*height: 28px;/)
  assert.doesNotMatch(source, /<span[\s\S]{0,80}class="colorItem iconfont"/)
})

test('基础样式颜色和彩虹线方案不再依赖鼠标点击容器', async () => {
  const source = await readFile(new URL('BaseStyle.vue', componentRoot), 'utf8')

  assert.equal((source.match(/<ColorTrigger/g) || []).length, 5)
  assert.doesNotMatch(source, /<span\s+[\s\S]{0,80}class="block"/)
  assert.match(source, /<button[\s\S]*class="optionItem"[\s\S]*:aria-pressed="isRainbowOptionSelected\(item\)"/)
  assert.match(source, /class="curRainbowLine"[\s\S]*:aria-expanded="rainbowLinesPopoverVisible"/)
  assert.doesNotMatch(source, /<span v-else @click="updateRainbowLinesConfig/)
})

test('所有脑图颜色弹层复用统一的具名触发器', async () => {
  const files = ['BaseStyle.vue', 'Style.vue', 'NodeOuterFrame.vue']
  const sources = await Promise.all(files.map(file => readFile(new URL(file, componentRoot), 'utf8')))
  const triggerSource = await readFile(new URL('ColorTrigger.vue', componentRoot), 'utf8')

  assert.equal(sources.reduce((count, source) => count + (source.match(/<ColorTrigger/g) || []).length, 0), 13)
  assert.equal(sources.every(source => source.includes("import ColorTrigger from './ColorTrigger.vue'")), true)
  assert.equal(sources.every(source => !/class="block"/.test(source)), true)
  assert.match(triggerSource, /<button[\s\S]*type="button"[\s\S]*:disabled="disabled"/)
  assert.match(triggerSource, /:aria-label="accessibleLabel"/)
  assert.match(triggerSource, /width: \{ type: Number, default: 32 \}/)
  assert.match(triggerSource, /background-image:[\s\S]*linear-gradient/)
  assert.match(triggerSource, /backgroundImage: isTransparent\.value \? undefined : 'none'/)
})
