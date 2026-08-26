import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)

async function readComponent(file) {
  return readFile(new URL(file, componentRoot), 'utf8')
}

test('只读侧栏白名单由状态层统一执行且禅模式不再绕过关闭规则', async () => {
  const [store, trigger, editor] = await Promise.all([
    readComponent('useStore.js'),
    readComponent('SidebarTrigger.vue'),
    readComponent('Edit.vue'),
  ])

  assert.match(store, /const READONLY_SAFE_SIDEBARS = new Set\(\[/)
  for (const sidebar of ['outline', 'shortcutKey', 'versionHistory', 'collaboratorManager', 'noteSidebar', 'comments']) {
    assert.match(store, new RegExp(`'${sidebar}'`))
  }
  assert.doesNotMatch(store, /'ai'/)
  assert.match(store, /export function isMindmapSidebarReadonlySafe/)
  assert.match(store, /function setActiveSidebar\(name\)[\s\S]*state\.isReadonly && !isMindmapSidebarReadonlySafe\(name\)[\s\S]*return false/)
  assert.match(store, /state\.isReadonly[\s\S]*!isMindmapSidebarReadonlySafe\(state\.activeSidebar\)[\s\S]*state\.activeSidebar = null/)

  assert.match(trigger, /list\.filter\(item => isMindmapSidebarReadonlySafe\(item\.value\)\)/)
  assert.match(trigger, /if \(isReadonly\.value && !isMindmapSidebarReadonlySafe\(item\?\.value\)\) return/)
  assert.match(editor, /isReadonly\.value && !isMindmapSidebarReadonlySafe\(sidebarName\)/)
})

test('只读状态允许查看节点备注但继续拒绝写入型侧栏', async () => {
  const { actions, store } = await import('../../components/MindMap/useStore.js')
  actions.resetState()
  try {
    actions.setIsReadonly(true)
    assert.equal(actions.setActiveSidebar('comments'), true)
    assert.equal(store.activeSidebar, 'comments')
    assert.equal(actions.setActiveSidebar('noteSidebar'), true)
    assert.equal(store.activeSidebar, 'noteSidebar')
    assert.equal(actions.setActiveSidebar('style'), false)
    assert.equal(store.activeSidebar, 'noteSidebar')
  } finally {
    actions.resetState()
  }
})

test('节点样式类侧栏在直接写入边界重新校验只读状态', async () => {
  const [nodeIcon, formula, structure, style, baseStyle] = await Promise.all([
    readComponent('NodeIconSidebar.vue'),
    readComponent('FormulaSidebar.vue'),
    readComponent('Structure.vue'),
    readComponent('Style.vue'),
    readComponent('BaseStyle.vue'),
  ])

  assert.match(nodeIcon, /:disabled="iconControlsDisabled \|\| !item\.tag"/)
  assert.match(nodeIcon, /const iconControlsDisabled = computed\(\(\) => isReadonly\.value \|\| activeNodes\.value\.length === 0\)/)
  assert.match(nodeIcon, /function setTag[\s\S]*if \(iconControlsDisabled\.value\) return[\s\S]*node\.setTag/)
  assert.doesNotMatch(nodeIcon, /node\.setIcon/)

  assert.match(formula, /:disabled="!canInsertFormula"/)
  assert.match(formula, /const canInsertFormula = computed[\s\S]*!isReadonly\.value[\s\S]*store\.activeSidebar === 'formulaSidebar'[\s\S]*node\?\.mindMap === activeMindMap/)
  assert.match(formula, /function confirm\(\)[\s\S]*if \(!canInsertFormula\.value \|\| !activeMindMap\) return/)
  assert.match(formula, /activeMindMap\.execCommand\('INSERT_FORMULA', str\)/)

  assert.match(structure, /:disabled="isReadonly"/)
  assert.match(structure, /function useLayout[\s\S]*isReadonly\.value[\s\S]*props\.mindMap\.setLayout/)

  assert.equal((style.match(/if \(store\.isReadonly\) return/g) || []).length >= 9, true)
  assert.match(style, /function update[\s\S]*if \(store\.isReadonly\) return[\s\S]*node\.setStyle/)

  assert.equal((baseStyle.match(/store\.isReadonly\) return/g) || []).length >= 4, true)
  assert.match(baseStyle, /function updateRainbowLinesConfig[\s\S]*if \(store\.isReadonly\) return/)
  assert.match(baseStyle, /function updateOuterFramePadding[\s\S]*if \(store\.isReadonly\) return/)
})

test('公式侧栏隔离插件请求、节点事件与脑图实例切换', async () => {
  const [formula, editor] = await Promise.all([
    readComponent('FormulaSidebar.vue'),
    readComponent('Edit.vue'),
  ])

  assert.match(formula, /function isCurrentPluginRequest\(requestId, mindMap\)[\s\S]*componentAlive[\s\S]*mindMap === props\.mindMap[\s\S]*store\.activeSidebar === 'formulaSidebar'/)
  assert.match(formula, /await ensureFormulaPlugin\(activeMindMap\)[\s\S]*if \(!isCurrentPluginRequest\(requestId, activeMindMap\)\) return/)
  assert.match(formula, /function handleNodeActive\(_, nodeList, sourceMindMap = null\)[\s\S]*resolveMindmapEventNodes\(nodeList, sourceMindMap, props\.mindMap\)[\s\S]*if \(nodes === null\) return/)
  assert.match(formula, /watch\(\(\) => props\.mindMap,[\s\S]*resetFormulaSession\(\)[\s\S]*actions\.setActiveSidebar\(null\)/)
  assert.match(formula, /onBeforeUnmount\(\(\) => \{\s*componentAlive = false\s*resetFormulaSession\(\)/)
  assert.match(editor, /forwardEvents\.forEach\(eventName => \{[\s\S]*bus\.emit\(eventName, \.\.\.args, mm\)/)
})

test('主题覆盖确认绑定当前侧栏、实例和组件生命周期', async () => {
  const theme = await readComponent('Theme.vue')

  assert.match(theme, /:disabled="themeChangePending \|\| isReadonly"/)
  assert.match(theme, /if \(!props\.mindMap \|\| themeChangePending\.value \|\| isReadonly\.value\) return/)
  assert.match(theme, /const operationId = \+\+themeOperationId/)
  assert.match(theme, /componentAlive[\s\S]*operationId === themeOperationId[\s\S]*activeMindMap === props\.mindMap[\s\S]*store\.activeSidebar === 'theme'[\s\S]*!isReadonly\.value/)
  assert.match(theme, /if \(!isCurrentOperation\(\)\) return\s*changeTheme/)
  assert.match(theme, /targetMindMap !== props\.mindMap \|\| isReadonly\.value/)
  assert.match(theme, /onBeforeUnmount[\s\S]*componentAlive = false[\s\S]*themeOperationId \+= 1/)
})
