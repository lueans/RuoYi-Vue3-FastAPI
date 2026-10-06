<template>
  <main class="app-container mindmapHelp">
    <header>
      <p class="eyebrow">脑图使用帮助</p>
      <h1>从第一张脑图开始</h1>
      <p>这里介绍常用操作，以及保存、协作和 AI 任务的状态说明。</p>
      <router-link v-if="canListMindmaps" class="helpLink" to="/mindmap/index">进入脑图工作台 →</router-link>
    </header>
    <nav aria-label="帮助目录" class="helpContents">
      <a v-for="section in sections" :key="section.id" :href="`#${section.id}`">{{ section.title }}</a>
    </nav>
    <section v-for="section in sections" :id="section.id" :key="section.id" :aria-labelledby="`${section.id}-title`">
      <h2 :id="`${section.id}-title`">{{ section.title }}</h2>
      <ol><li v-for="text in section.steps" :key="text">{{ text }}</li></ol>
    </section>
  </main>
</template>

<script setup>
import { computed } from 'vue'
import useUserStore from '@/store/modules/user'
import { hasAnyPermission, MINDMAP_FILE_PERMISSIONS } from '@/utils/mindmap-permission'
const userStore = useUserStore()
const canListMindmaps = computed(() => hasAnyPermission(userStore.permissions, MINDMAP_FILE_PERMISSIONS.list))
const sections = [
  { id: 'create', title: '创建与整理脑图', steps: [
    '在“我的脑图”点击“新建脑图”，填写名称后选择“创建并编辑”。说明与所属目录可以选填。',
    '选中节点，使用工具栏的“主题”“子主题”添加内容；双击节点编辑文字。画布选中节点时，Enter 添加同级节点，Tab 添加子节点。',
    '列表可以切换卡片或表格视图，按名称、状态和标签筛选。窄屏点击“目录”展开文件夹；文件的“更多”菜单提供移动、复制、归档等操作。',
  ] },
  { id: 'save', title: '保存状态与本地草稿', steps: [
    '内容修改会自动保存；也可点击“保存”或按 Ctrl / ⌘ + S。离开前留意保存状态，保存失败不代表内容已经同步到服务器。',
    '断网、自动保存失败或协作会话终止时，按页面提示重连或恢复。未同步内容可能保存在当前账号、当前浏览器的本地草稿中。',
    '在脑图列表打开“本地草稿”，先下载或恢复并确认内容，再删除不需要的草稿。其他设备或浏览器不会自动拥有这些本地草稿。',
  ] },
  { id: 'navigate', title: '大纲、搜索与阅读', steps: [
    '使用“大纲”浏览节点或打开大纲编辑；底部“更多编辑器操作”也提供大纲、版本历史和快捷键入口。',
    '搜索节点可使用顶部搜索或 Ctrl / ⌘ + F；列表中的“搜索全部节点”用于跨脑图查找。画布底部可缩放、回到根节点或适应画布。',
    '只读预览不能修改内容。若有编辑权限，可使用“进入编辑”；归档脑图需先在列表恢复。只读状态仍可调整编辑器设置中的个人浏览偏好。',
    '大纲编辑中，Shift + Enter 换行，Tab 添加子节点，Enter 添加同级节点，Alt + ↑ / ↓ 切换编辑节点，Shift + Tab 移到关闭按钮，Esc 关闭大纲编辑。',
  ] },
  { id: 'tags', title: '使用标签', steps: [
    '在画布选择节点后打开“标签”，点击常用标签应用或取消；“更多标签”可以搜索并创建标签。',
    '标签管理中可创建分组、调整顺序和样式。分组可设为单选；同一节点选择新标签时会替换该组原有标签。',
    '编辑标签定义会影响引用它的脑图和节点，保存前查看影响范围。“解绑并归档”会移除现有节点上的引用，历史版本快照保留。',
  ] },
  { id: 'collaborate', title: '分享、协作与版本', steps: [
    '所有者可通过“分享”管理链接，通过“协作者管理”授予成员查看或编辑权限。与我共享中的文件按所有者授予的权限开放。',
    '多人协作时，同一节点的文字编辑可能被占用；按照提示等待对方完成。不要用刷新页面代替保存或恢复。',
    '“版本历史”可查看已有快照。恢复版本前请确认目标版本和影响；归档保留内容、版本和分享，永久删除无法撤销。',
  ] },
  { id: 'ai', title: 'AI 脑图与任务结果', steps: [
    '打开“AI 脑图”，选择可用 Agent，说明要创建、修改或讨论的内容。运行前查看当前任务范围及页面提供的确认信息。',
    '任务运行中可阅读过程与结果状态；停止任务不代表已经提交的修改会自动撤销。以本轮结果回执和保存状态为准。',
    '离开后可从 AI 任务中心找回任务。需要采纳、审核、保存或恢复时，按任务卡片给出的操作继续；不要只凭 AI 回复文字判断已经保存。',
  ] },
]
</script>

<style scoped>
.mindmapHelp { max-width: 980px; margin: 0 auto; color: var(--el-text-color-primary); }
header,section { padding: 24px; margin-bottom: 20px; border: 1px solid var(--el-border-color-light); border-radius: 12px; background: var(--el-bg-color); }
header p,.eyebrow,li { color: var(--el-text-color-regular); line-height: 1.85; }
h1 { font-size: 28px; margin: 8px 0 12px; } h2 { margin: 0 0 16px; font-size: 20px; }
.helpContents { display: flex; flex-wrap: wrap; gap: 12px 20px; margin: 0 0 20px; padding: 12px 4px; }
.helpContents a,.helpLink { color: var(--el-color-primary); text-decoration: underline; text-underline-offset: 3px; }
.helpLink { display: inline-block; margin-top: 10px; } a:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 4px; }
section { scroll-margin-top: 110px; } ol { margin: 0; padding-left: 22px; } li + li { margin-top: 10px; }
@media (max-width: 600px) { header,section { padding: 18px; } h1 { font-size: 24px; } }
</style>
