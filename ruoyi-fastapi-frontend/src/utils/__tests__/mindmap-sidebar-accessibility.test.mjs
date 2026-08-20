import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)
const sidebarSourceUrl = new URL('Sidebar.vue', componentRoot)
const triggerSourceUrl = new URL('SidebarTrigger.vue', componentRoot)
const searchSourceUrl = new URL('Search.vue', componentRoot)
const toolbarSourceUrl = new URL('Toolbar.vue', componentRoot)
const navigatorSourceUrl = new URL('NavigatorToolbar.vue', componentRoot)
const editSourceUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const editorSourceUrl = new URL('Edit.vue', componentRoot)

test('隐藏侧栏从可访问树和焦点顺序隔离，并提供语义化关闭入口', async () => {
  const source = await readFile(sidebarSourceUrl, 'utf8')

  assert.match(source, /:inert="!show"/)
  assert.match(source, /:aria-hidden="show \? undefined : 'true'"/)
  assert.match(source, /role="complementary"/)
  assert.match(source, /role="heading" aria-level="2"/)
  assert.match(source, /<button[\s\S]*?ref="closeButtonRef"[\s\S]*?type="button"/)
  assert.match(source, /@keydown\.esc\.stop="onEscape"/)
})

test('侧栏打开和关闭具备完整焦点生命周期，并同步全局激活状态', async () => {
  const [sidebar, trigger] = await Promise.all([
    readFile(sidebarSourceUrl, 'utf8'),
    readFile(triggerSourceUrl, 'utf8'),
  ])

  assert.match(sidebar, /bus\.on\('focusActiveSidebar', focusWhenOpen\)/)
  assert.match(sidebar, /closeButtonRef\.value\?\.focus\(\)/)
  assert.match(sidebar, /actions\.setActiveSidebar\(null\)/)
  assert.match(sidebar, /bus\.emit\('focusSidebarTrigger', sidebarName\)/)
  assert.match(sidebar, /focusReturnTarget = document\.activeElement/)
  assert.match(sidebar, /returnTarget\?\.isConnected && !returnTarget\.closest\?\.\('\[inert\]'\)/)
  assert.match(sidebar, /returnTarget\.focus\?\.\(\)/)
  assert.match(trigger, /:ref="el => setTriggerRef\(item\.value, el\)"/)
  assert.match(trigger, /triggerRefs\.get\(name\)\?\.focus\(\)/)
  assert.match(trigger, /bus\.on\('focusSidebarTrigger', focusTrigger\)/)
})

test('所有用户主动打开侧栏的入口都会请求聚焦侧栏', async () => {
  const sources = await Promise.all([
    readFile(toolbarSourceUrl, 'utf8'),
    readFile(navigatorSourceUrl, 'utf8'),
    readFile(editSourceUrl, 'utf8'),
  ])

  assert.match(sources[0], /event: 'openSidebar'/)
  assert.equal(sources.slice(1).every(source => source.includes("bus.emit('focusActiveSidebar')")), true)
})

test('服务端锁定的只读文件不会暴露可执行的整理布局命令', async () => {
  const source = await readFile(navigatorSourceUrl, 'utf8')

  assert.match(source, /command="fitCanvas" :disabled="lockedReadonly"/)
  assert.match(source, /if \(props\.lockedReadonly\) return[\s\S]*?bus\.emit\('execCommand', 'RESET_LAYOUT'\)/)
})

test('搜索面板打开时关闭侧栏，退出搜索后恢复有效的原焦点', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')

  assert.match(source, /focusReturnTarget = document\.activeElement/)
  assert.match(source, /bus\.emit\('closeSideBar'\)/)
  assert.match(source, /returnTarget\?\.isConnected && !returnTarget\.closest\?\.\('\[inert\]'\)/)
  assert.match(source, /returnTarget\.focus\?\.\(\)/)
})

test('常规侧栏仅在激活时挂载，画布上下文侧栏保留事件监听生命周期', async () => {
  const source = await readFile(editorSourceUrl, 'utf8')

  const lazySidebarGuards = {
    OutlineSidebar: 'outline',
    MmStyle: 'nodeStyle',
    BaseStyle: 'baseStyle',
    Theme: 'theme',
    Structure: 'structure',
    ShortcutKey: 'shortcutKey',
    Setting: 'setting',
    FormulaSidebar: 'formulaSidebar',
    NodeIconSidebar: 'nodeIconSidebar',
    VersionHistory: 'versionHistory',
    CollaboratorManager: 'collaboratorManager',
  }
  for (const [component, sidebarName] of Object.entries(lazySidebarGuards)) {
    assert.equal(
      source.includes(`<${component}`) && source.includes(`activeSidebar === '${sidebarName}'`),
      true,
      `${component} 必须由 activeSidebar 控制挂载`,
    )
  }

  assert.match(source, /<AssociativeLineStyle v-if="mindMap"/)
  assert.match(source, /<NodeOuterFrame v-if="mindMap"/)
  assert.match(source, /<NodeNoteSidebar v-if="mindMap"/)
  assert.equal((source.match(/<NodeIconSidebar/g) || []).length, 1)
})

test('图标侧栏只有一个按需实例，懒挂载面板声明首次打开契约', async () => {
  const toolbar = await readFile(toolbarSourceUrl, 'utf8')
  const editor = await readFile(editorSourceUrl, 'utf8')
  const sidebar = await readFile(sidebarSourceUrl, 'utf8')
  const lazySidebarFiles = [
    'Style.vue',
    'BaseStyle.vue',
    'Theme.vue',
    'Structure.vue',
    'OutlineSidebar.vue',
    'Setting.vue',
    'ShortcutKey.vue',
    'VersionHistory.vue',
    'CollaboratorManager.vue',
    'NodeIconSidebar.vue',
    'FormulaSidebar.vue',
  ]

  assert.equal(toolbar.includes("import NodeIcon from './NodeIconSidebar.vue'"), false)
  assert.match(toolbar, /event: 'openSidebar', args: \['nodeIconSidebar'\]/)
  assert.match(editor, /<NodeIconSidebar[\s\S]*?activeSidebar === 'nodeIconSidebar'/)
  assert.match(editor, /bus\.on\('openSidebar', onOpenSidebar\)/)
  assert.match(sidebar, /openOnMount: \{ type: Boolean, default: false \}/)
  assert.match(sidebar, /if \(props\.openOnMount\) open\(\)/)

  const sources = await Promise.all(
    lazySidebarFiles.map(file => readFile(new URL(file, componentRoot), 'utf8')),
  )
  assert.equal(sources.every(source => source.includes('open-on-mount')), true)
  assert.equal(sources.every(source => source.includes('{ immediate: true }')), true)
  const nodeIconSidebar = sources[lazySidebarFiles.indexOf('NodeIconSidebar.vue')]
  assert.match(nodeIconSidebar, /const props = defineProps\(\{[\s\S]*mindMap:/)
  assert.match(nodeIconSidebar, /<button v-for="item in group\.list"[\s\S]*:aria-pressed="isSelected/)
  assert.match(nodeIconSidebar, /toggleNodeIconAcrossLists/)
  assert.match(nodeIconSidebar, /getCommonNodeIcons/)
  assert.match(nodeIconSidebar, /activeNodes\.value\.length === 0[\s\S]*actions\.setActiveSidebar\(null\)/)
  assert.match(nodeIconSidebar, /:deep\(svg\)/)
})

test('大纲与公式侧栏的高频条目使用原生键盘控件', async () => {
  const [outline, formula] = await Promise.all([
    readFile(new URL('OutlineSidebar.vue', componentRoot), 'utf8'),
    readFile(new URL('FormulaSidebar.vue', componentRoot), 'utf8'),
  ])

  assert.match(outline, /<button[\s\S]*class="outline-expand"[\s\S]*:aria-expanded="entry\.item\.expanded"/)
  assert.match(outline, /<button[\s\S]*class="outline-target outline-text"[\s\S]*@click="goToNode/)
  assert.doesNotMatch(outline, /class="outline-node"[\s\S]{0,120}@click=/)
  assert.match(formula, /class="formulaList customScrollbar" role="list"/)
  assert.match(formula, /<button[\s\S]*class="text"[\s\S]*:aria-label="`使用公式/)
  assert.doesNotMatch(formula, /<div class="text" @click=/)
})
