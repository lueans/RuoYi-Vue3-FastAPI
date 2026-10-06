<template>
  <main class="app-container homeWorkspace">
    <header class="welcomeCard">
      <el-avatar :size="52" :src="userStore.avatar" aria-hidden="true" />
      <div>
        <p class="eyebrow">你的工作空间</p>
        <h1>你好，{{ userStore.nickName || userStore.name || '用户' }}</h1>
        <p>用脑图整理想法、管理知识，与成员一起协作。</p>
      </div>
    </header>
    <section class="workspaceCards" aria-label="开始使用">
      <router-link v-if="canListMindmaps" class="workspaceCard primaryCard" to="/mindmap/index">
        <el-icon aria-hidden="true"><Files /></el-icon>
        <h2>我的脑图</h2><p>创建脑图，继续编辑已有内容，或找回本地草稿。</p><span>进入脑图工作台 →</span>
      </router-link>
      <router-link v-if="canListMindmaps" class="workspaceCard" :to="{ path: '/mindmap/index', query: { scope: 'shared' } }">
        <el-icon aria-hidden="true"><Share /></el-icon>
        <h2>与我共享</h2><p>查看他人授权的脑图，按授予的权限参与协作。</p><span>查看共享脑图 →</span>
      </router-link>
      <router-link v-if="canListTags" class="workspaceCard" to="/mindmap/tags">
        <el-icon aria-hidden="true"><CollectionTag /></el-icon>
        <h2>标签管理</h2><p>整理常用标签和分组，让节点分类保持一致。</p><span>管理标签 →</span>
      </router-link>
      <router-link class="workspaceCard" to="/help/mindmap">
        <el-icon aria-hidden="true"><QuestionFilled /></el-icon>
        <h2>脑图使用帮助</h2><p>了解创建、自动保存、分享协作与 AI 脑图的基本用法。</p><span>阅读快速入门 →</span>
      </router-link>
    </section>
    <p v-if="!canListMindmaps" class="permissionNotice" role="status">当前账号尚未获得脑图列表权限。如需使用，请联系管理员开通；你仍可查看使用帮助。</p>
  </main>
</template>

<script setup>
import { computed } from 'vue'
import { CollectionTag, Files, QuestionFilled, Share } from '@element-plus/icons-vue'
import useUserStore from '@/store/modules/user'
import { hasAnyPermission, MINDMAP_FILE_PERMISSIONS } from '@/utils/mindmap-permission'
defineOptions({ name: 'WorkspaceHome' })
const userStore = useUserStore()
const canListMindmaps = computed(() => hasAnyPermission(userStore.permissions, MINDMAP_FILE_PERMISSIONS.list))
const canListTags = computed(() => hasAnyPermission(userStore.permissions, ['mindmap:tag:list']))
</script>

<style scoped lang="scss">
.homeWorkspace { max-width: 1280px; margin: 0 auto; }
.welcomeCard { display: flex; align-items: center; gap: 18px; margin-bottom: 28px; padding: 28px; border-radius: 14px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); }
h1 { margin: 6px 0 10px; font-size: 26px; color: var(--el-text-color-primary); overflow-wrap: anywhere; }
p { margin: 0; color: var(--el-text-color-regular); line-height: 1.7; }
.eyebrow { color: var(--el-text-color-secondary); font-size: 13px; }
.workspaceCards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.workspaceCard { display: flex; min-width: 0; flex-direction: column; align-items: flex-start; padding: 28px; border: 1px solid var(--el-border-color-light); border-radius: 14px; background: var(--el-bg-color); color: var(--el-text-color-primary); text-decoration: none; }
.workspaceCard > .el-icon { font-size: 28px; color: var(--el-color-primary); }
.workspaceCard h2 { font-size: 18px; margin: 18px 0 10px; }
.workspaceCard span { color: var(--el-color-primary); margin-top: 20px; font-weight: 600; }
.workspaceCard:hover { border-color: var(--el-color-primary); }
.workspaceCard:focus-visible { outline: 3px solid var(--el-color-primary); outline-offset: 3px; }
.primaryCard { background: var(--el-color-primary-light-9); }
.permissionNotice { margin-top: 20px; }
@media (max-width: 600px) { .workspaceCards { grid-template-columns: 1fr; } .welcomeCard { align-items: flex-start; padding: 20px; } .workspaceCard { padding: 22px; } h1 { font-size: 22px; } }
</style>
