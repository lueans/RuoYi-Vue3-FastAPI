import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)
const sidebarSourceUrl = new URL('Sidebar.vue', componentRoot)
const inspectorSourceUrl = new URL('PropertyInspector.vue', componentRoot)
const styleSourceUrl = new URL('Style.vue', componentRoot)
const baseStyleSourceUrl = new URL('BaseStyle.vue', componentRoot)
const structureSourceUrl = new URL('Structure.vue', componentRoot)
const themeSourceUrl = new URL('Theme.vue', componentRoot)
const triggerSourceUrl = new URL('SidebarTrigger.vue', componentRoot)
const storeSourceUrl = new URL('useStore.js', componentRoot)
const searchSourceUrl = new URL('Search.vue', componentRoot)
const toolbarSourceUrl = new URL('Toolbar.vue', componentRoot)
const navigatorSourceUrl = new URL('NavigatorToolbar.vue', componentRoot)
const outlineSourceUrl = new URL('OutlineSidebar.vue', componentRoot)
const shortcutSourceUrl = new URL('ShortcutKey.vue', componentRoot)
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
  const [sidebar, inspector, trigger] = await Promise.all([
    readFile(sidebarSourceUrl, 'utf8'),
    readFile(inspectorSourceUrl, 'utf8'),
    readFile(triggerSourceUrl, 'utf8'),
  ])

  assert.match(sidebar, /bus\.on\('focusActiveSidebar', focusWhenOpen\)/)
  assert.match(sidebar, /closeButtonRef\.value\?\.focus\(\)/)
  assert.match(sidebar, /actions\.setActiveSidebar\(null\)/)
  assert.match(sidebar, /bus\.emit\('focusSidebarTrigger', sidebarName\)/)
  assert.match(sidebar, /focusReturnTarget = document\.activeElement/)
  assert.match(sidebar, /returnTarget\?\.isConnected && !returnTarget\.closest\?\.\('\[inert\]'\)/)
  assert.match(sidebar, /returnTarget\.focus\?\.\(\)/)
  assert.match(inspector, /role="complementary"/)
  assert.match(inspector, /@keydown\.esc\.stop="closeInspector"/)
  assert.match(inspector, /bus\.on\('focusActiveSidebar', focusWhenOpen\)/)
  assert.match(inspector, /closeButtonRef\.value\?\.focus\(\)/)
  assert.match(inspector, /actions\.setActiveSidebar\(null\)/)
  assert.match(inspector, /returnTarget\?\.isConnected && !returnTarget\.closest\?\.\('\[inert\]'\)/)
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

test('搜索面板可与右侧栏并存，筛选弹窗仍收起侧栏且退出后恢复原焦点', async () => {
  const source = await readFile(searchSourceUrl, 'utf8')
  const showSearchBlock = source.match(/function showSearch\(\) \{[\s\S]*?\n\}/)?.[0] || ''
  const showFilterBlock = source.match(/function showFilter\(\) \{[\s\S]*?\n\}/)?.[0] || ''

  assert.match(source, /focusReturnTarget = document\.activeElement/)
  assert.doesNotMatch(showSearchBlock, /closeSideBar/)
  assert.match(showFilterBlock, /bus\.emit\('closeSideBar'\)/)
  assert.match(source, /bus\.emit\('searchPanelVisibilityChange', visible && mode === 'search'\)/)
  assert.match(source, /returnTarget\?\.isConnected && !returnTarget\.closest\?\.\('\[inert\]'\)/)
  assert.match(source, /returnTarget\.focus\?\.\(\)/)
})

test('节点大纲和快捷键停靠左侧并与左侧搜索面板互斥', async () => {
  const [sidebar, outline, shortcut, search, edit] = await Promise.all([
    readFile(sidebarSourceUrl, 'utf8'),
    readFile(outlineSourceUrl, 'utf8'),
    readFile(shortcutSourceUrl, 'utf8'),
    readFile(searchSourceUrl, 'utf8'),
    readFile(editSourceUrl, 'utf8'),
  ])

  assert.match(sidebar, /placement: \{[\s\S]*?default: 'right'/)
  assert.match(sidebar, /isLeft: computed|const isLeft = computed/)
  assert.match(sidebar, /&\.isLeft \{[\s\S]*?left: calc\(-1 \* var\(--mindmap-side-panel-width/)
  assert.match(sidebar, /&\.isLeft[\s\S]*?&\.show \{[\s\S]*?left: var\(--mindmap-activity-width/)
  assert.match(outline, /<Sidebar[^>]*placement="left"/)
  assert.match(shortcut, /<Sidebar[^>]*placement="left"/)
  assert.match(search, /leftSidebarNames\.has\(store\.activeSidebar\)[\s\S]*?actions\.setActiveSidebar\(null\)/)
  assert.match(search, /leftSidebarNames\.has\(sidebarName\) \|\| window\.innerWidth <= 760/)
  assert.match(edit, /const leftSidebarNames = new Set\(\['outline', 'shortcutKey'\]\)/)
  assert.match(edit, /'has-left-panel': isLeftSidebarActive/)
  assert.match(edit, /'has-right-panel': Boolean\(activeSidebar && !isLeftSidebarActive\)/)
  assert.match(edit, /&\.has-left-panel \{[\s\S]*?--mindmap-workspace-left:/)
})

test('常规侧栏仅在激活时挂载，画布上下文侧栏保留事件监听生命周期', async () => {
  const source = await readFile(editorSourceUrl, 'utf8')

  const lazySidebarGuards = {
    OutlineSidebar: 'outline',
    ShortcutKey: 'shortcutKey',
    Setting: 'setting',
    FormulaSidebar: 'formulaSidebar',
    NodeTagSidebar: 'nodeTagSidebar',
    VersionHistory: 'versionHistory',
    CollaboratorManager: 'collaboratorManager',
  }

  assert.match(source, /<PropertyInspector[\s\S]*?v-if="mindMap && hasPropertyInspector"/)
  assert.match(source, /const propertySidebarNames = new Set\(\['nodeStyle', 'baseStyle', 'structure', 'theme'\]\)/)
  assert.match(source, /const hasPropertyInspector = computed/)
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
  assert.doesNotMatch(source, /<NodeIconSidebar|NodeIconToolbar/)
})

test('节点标记入口迁移到标签弹窗，其他懒挂载面板保留首次打开契约', async () => {
  const toolbar = await readFile(toolbarSourceUrl, 'utf8')
  const editor = await readFile(editorSourceUrl, 'utf8')
  const sidebar = await readFile(sidebarSourceUrl, 'utf8')
  const lazySidebarFiles = [
    'OutlineSidebar.vue',
    'Setting.vue',
    'ShortcutKey.vue',
    'VersionHistory.vue',
    'CollaboratorManager.vue',
    'NodeIconSidebar.vue',
    'FormulaSidebar.vue',
  ]

  assert.equal(toolbar.includes("import NodeIcon from './NodeIconSidebar.vue'"), false)
  assert.match(toolbar, /tag: \{ icon: 'iconbiaoqian', event: 'openSidebar', args: \['nodeTagSidebar'\] \}/)
  assert.match(editor, /<NodeTagSidebar[\s\S]*activeSidebar === 'nodeTagSidebar'/)
  assert.doesNotMatch(editor, /<NodeIconSidebar|NodeIconToolbar/)
  assert.match(editor, /bus\.on\('openSidebar', onOpenSidebar\)/)
  assert.match(sidebar, /openOnMount: \{ type: Boolean, default: false \}/)
  assert.match(sidebar, /if \(props\.openOnMount\) open\(\)/)

  const sources = await Promise.all(
    lazySidebarFiles.map(file => readFile(new URL(file, componentRoot), 'utf8')),
  )
  assert.equal(sources.every(source => source.includes('open-on-mount')), true)
  assert.equal(sources.every(source => source.includes('{ immediate: true }')), true)
  const nodeTagSidebar = sources[lazySidebarFiles.indexOf('NodeIconSidebar.vue')]
  assert.match(nodeTagSidebar, /listTags\(\{/)
  assert.match(nodeTagSidebar, /listTagCategories\(\)/)
  assert.match(nodeTagSidebar, /category\.showOnHome/)
  assert.match(nodeTagSidebar, /category\.selectionMode/)
  assert.match(nodeTagSidebar, /removeMindmapSingleSelectionPeers/)
  assert.match(nodeTagSidebar, /categoryId: tag\.categoryId/)
  assert.match(nodeTagSidebar, /async function loadTagCatalog\(requestId\)/)
  assert.match(nodeTagSidebar, /tagsByCategoryId\.get\(String\(category\.id\)\)/)
  assert.doesNotMatch(nodeTagSidebar, /Promise\.all\([\s\S]*homeCategories\.map/)
  assert.doesNotMatch(nodeTagSidebar, /listTags\(\{[\s\S]{0,100}categoryId/)
  assert.match(nodeTagSidebar, /node\.setTag\(nextTags/)
  assert.doesNotMatch(nodeTagSidebar, /node\.setIcon\(/)
})

test('统一属性检查器提供语义化页签、停靠布局和可撤销的节点样式重置入口', async () => {
  const [inspector, editor, trigger] = await Promise.all([
    readFile(inspectorSourceUrl, 'utf8'),
    readFile(editorSourceUrl, 'utf8'),
    readFile(triggerSourceUrl, 'utf8'),
  ])

  assert.match(inspector, /role="tablist"/)
  assert.match(inspector, /role="tab"/)
  assert.match(inspector, /role="tabpanel"/)
  assert.match(inspector, /:aria-selected="activeTab === tab\.value"/)
  assert.match(inspector, /event\.key === 'ArrowRight'/)
  assert.match(inspector, /event\.key === 'ArrowLeft'/)
  assert.match(inspector, /REMOVE_ALL_NODE_CUSTOM_STYLES/)
  assert.match(inspector, /activeNodes\.length === 0 \|\| isReadonly/)
  assert.match(inspector, /<MmStyle[\s\S]*?embedded/)
  assert.match(inspector, /<Structure[\s\S]*?embedded/)
  assert.match(inspector, /<BaseStyle[\s\S]*?embedded/)
  assert.match(inspector, /<Theme[\s\S]*?embedded/)
  assert.match(inspector, /class="applicationState" role="status" aria-live="polite"/)
  assert.match(inspector, /v-show="feedbackActive" class="applicationState"/)
  assert.match(inspector, /return `已选择 \$\{activeNodes\.value\.length\} 个节点`/)
  assert.match(inspector, /width: var\(--mindmap-inspector-width, 300px\)/)
  assert.match(inspector, /margin: 0;\s*padding: 0;/)
  assert.match(inspector, /v-if="activeNodes\.length > 0"/)
  assert.match(inspector, /class="nodeEmptyState"/)
  assert.match(inspector, /@click="selectTab\('canvas', true\)"/)
  assert.match(inspector, /@click="selectTab\('theme', true\)"/)
  assert.match(inspector, /announceApplied\('节点样式已应用'\)/)
  assert.match(inspector, /应用到整张脑图/)
  assert.match(inspector, /需要恢复时可使用顶部撤销/)
  assert.match(inspector, /ref="inspectorBodyRef" class="inspectorBody customScrollbar"/)
  assert.match(inspector, /inspectorBodyRef\.value\.scrollTop = 0/)
  assert.match(editor, /left: calc\(var\(--mindmap-workspace-left/)
  assert.match(editor, /right: calc\(var\(--mindmap-workspace-right/)
  assert.match(editor, /watch\(\[activeSidebar, hasSearchPanel\]/)
  assert.match(editor, /mindMap\.value\?\.resize\?\.\(\)/)
  assert.match(trigger, /isPropertyInspectorActive/)
})

test('中屏覆盖右侧面板且移动端统一收口到 760px 断点', async () => {
  const [edit, sidebar, inspector, search, navigator] = await Promise.all([
    readFile(editSourceUrl, 'utf8'),
    readFile(sidebarSourceUrl, 'utf8'),
    readFile(inspectorSourceUrl, 'utf8'),
    readFile(searchSourceUrl, 'utf8'),
    readFile(navigatorSourceUrl, 'utf8'),
  ])

  assert.match(edit, /@media \(max-width: 1439px\) and \(min-width: 761px\)[\s\S]*?--mindmap-workspace-right: var\(--mindmap-activity-width\)/)
  assert.match(sidebar, /@media \(max-width: 1439px\) and \(min-width: 761px\)/)
  assert.match(inspector, /@media \(max-width: 1439px\) and \(min-width: 761px\)/)
  assert.match(inspector, /@media \(max-width: 760px\)[\s\S]*?right: 0;[\s\S]*?bottom: 52px;/)
  assert.match(search, /@media \(max-width: 760px\)[\s\S]*?\.searchContainer:not\(\.filterDialog\)/)
  assert.match(navigator, /@media screen and \(max-width: 760px\)/)
})

test('节点属性分组可通过键盘折叠，文字快捷控件暴露原生按钮语义', async () => {
  const source = await readFile(styleSourceUrl, 'utf8')

  assert.match(source, /<details class="styleSection" open>/)
  assert.match(source, /<summary class="title noTop">/)
  assert.match(source, /<el-icon class="sectionChevron"><ArrowUp \/><\/el-icon>/)
  assert.match(source, /role="group" aria-label="常用文字颜色"/)
  assert.match(source, /<span>更多<\/span>\s*<el-icon><ArrowDown \/><\/el-icon>/)
  assert.match(source, /class="quickColorButton"/)
  assert.match(source, /:aria-pressed="normalizeColor\(style\.color\) === normalizeColor\(color\)"/)
  assert.match(source, /type="button"[\s\S]*?aria-label="加粗"[\s\S]*?:aria-pressed="style\.fontWeight === 'bold'"/)
  assert.match(source, /type="button"[\s\S]*?aria-label="斜体"[\s\S]*?:aria-pressed="style\.fontStyle === 'italic'"/)
  assert.match(source, /role="group" aria-label="文字样式"/)
  assert.match(source, /aria-label="下划线"[\s\S]*?:aria-pressed="style\.textDecoration === 'underline'"/)
  assert.match(source, /aria-label="中划线"[\s\S]*?:aria-pressed="style\.textDecoration === 'line-through'"/)
  assert.match(source, /aria-label="减小字号"[\s\S]*?@click="stepFontSize\(-1\)"/)
  assert.match(source, /aria-label="增大字号"[\s\S]*?@click="stepFontSize\(1\)"/)
  assert.match(source, /role="group" aria-label="文字对齐方式"/)
  assert.match(source, /:aria-pressed="style\.textAlign === item\.value"/)
  assert.match(source, /function toggleTextDecoration[\s\S]*?update\('textDecoration'\)/)
  assert.match(source, /function setTextAlign[\s\S]*?update\('textAlign'\)/)
  assert.equal((source.match(/class="fieldBlock fullSpanField"/g) || []).length >= 2, true)
  assert.match(source, /:label="`\$\{item\}px`"/)
  assert.match(source, /\.fullSpanField \{\s*grid-column: 1 \/ -1/)
})

test('画布属性与全局样式支持键盘折叠，布局卡片暴露当前选中状态', async () => {
  const [inspector, baseStyle, structure] = await Promise.all([
    readFile(inspectorSourceUrl, 'utf8'),
    readFile(baseStyleSourceUrl, 'utf8'),
    readFile(structureSourceUrl, 'utf8'),
  ])

  assert.match(inspector, /<details class="canvasSection" open>/)
  assert.match(inspector, /<summary class="canvasSectionSummary">/)
  assert.match(baseStyle, /<details class="baseStyleSection" open>/)
  assert.equal((baseStyle.match(/<details class="baseStyleSection" open>/g) || []).length, 2)
  assert.match(baseStyle, /<summary class="title noTop">/)
  assert.match(baseStyle, /<el-icon class="sectionChevron"><ArrowUp \/><\/el-icon>/)
  assert.match(structure, /<details ref="layoutPickerRef" class="layoutPicker"/)
  assert.match(structure, /<summary ref="layoutSummaryRef" class="currentLayoutCard">/)
  assert.match(structure, /当前布局 · 点击更换/)
  assert.match(structure, /item !== currentLayout\.value/)
  assert.match(structure, /layoutPickerRef\.value\.open = false/)
  assert.match(structure, /layoutSummaryRef\.value\?\.focus\(\)/)
  assert.match(structure, /class="layoutName"/)
})

test('格式入口优先服务当前选区，并保留最近一次全局设置上下文', async () => {
  const [trigger, store] = await Promise.all([
    readFile(triggerSourceUrl, 'utf8'),
    readFile(storeSourceUrl, 'utf8'),
  ])

  assert.match(trigger, /item\.value === 'nodeStyle'[\s\S]*?resolveFormatSidebar\(\)/)
  assert.match(trigger, /activeNodeList \|\| \[\]/)
  assert.match(trigger, /if \(hasActiveNodes\) return 'nodeStyle'/)
  assert.match(trigger, /\['baseStyle', 'structure', 'theme'\]\.includes\(store\.lastPropertySidebar\)/)
  assert.match(store, /lastPropertySidebar: 'baseStyle'/)
  assert.match(store, /GLOBAL_PROPERTY_SIDEBARS = new Set\(\['baseStyle', 'structure', 'theme'\]\)/)
  assert.match(store, /if \(GLOBAL_PROPERTY_SIDEBARS\.has\(name\)\) state\.lastPropertySidebar = name/)
  assert.doesNotMatch(store, /new Set\(\['nodeStyle', 'baseStyle', 'structure', 'theme'\]\)/)
})

test('桌面只读页去除与顶部导航重复的侧栏入口，窄屏仍保留完整访问路径', async () => {
  const [trigger, navigator] = await Promise.all([
    readFile(triggerSourceUrl, 'utf8'),
    readFile(navigatorSourceUrl, 'utf8'),
  ])

  assert.match(trigger, /const readonlyHeaderSidebarNames = new Set\(\['outline', 'versionHistory'\]\)/)
  assert.match(trigger, /if \(viewportWidth\.value > 760\)/)
  assert.match(trigger, /!readonlyHeaderSidebarNames\.has\(item\.value\)/)
  assert.match(trigger, /activeSidebar\.value === item\.value/)
  assert.match(trigger, /viewportWidth\.value = window\.innerWidth/)
  assert.match(navigator, /command="format"[\s\S]*?>[\s\S]*?格式/)
  assert.match(navigator, /command="formulaSidebar"[\s\S]*?>[\s\S]*?公式/)
  assert.match(navigator, /command === 'format'[\s\S]*?actions\.setActiveSidebar\(targetSidebar\)/)
  assert.match(navigator, /command === 'formulaSidebar'[\s\S]*?actions\.setActiveSidebar\('formulaSidebar'\)/)
})

test('主题面板会定位当前主题分组，并为主题卡片提供可感知的选中态', async () => {
  const source = await readFile(themeSourceUrl, 'utf8')

  assert.match(source, /function syncActiveThemeGroup\(\)/)
  assert.match(source, /group\.list\.some\(theme => theme\.value === currentTheme\.value\)/)
  assert.match(source, /selectedTheme,[\s\S]*?group\.list\.filter\(item => item\.value !== currentTheme\.value\)/)
  assert.match(source, /:aria-pressed="item\.value === currentTheme"/)
  assert.match(source, /class="activeMark" aria-hidden="true"/)
  assert.match(source, /<small v-if="item\.value === currentTheme">当前<\/small>/)
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
