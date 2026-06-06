<template>
  <div class="collaborators" v-if="collaborators.length > 0">
    <el-tooltip
      v-for="user in displayUsers"
      :key="user.id"
      :content="user.name"
      placement="bottom"
    >
      <el-avatar :size="28" :src="user.avatar || undefined">
        {{ user.name?.charAt(0) || '?' }}
      </el-avatar>
    </el-tooltip>
    <el-tooltip v-if="extraCount > 0" :content="`还有 ${extraCount} 人`" placement="bottom">
      <el-avatar :size="28" class="extra-count">+{{ extraCount }}</el-avatar>
    </el-tooltip>
  </div>
</template>

<script setup>
const props = defineProps({
  collaborators: { type: Array, default: () => [] },
  maxDisplay: { type: Number, default: 5 }
})

const displayUsers = computed(() => props.collaborators.slice(0, props.maxDisplay))
const extraCount = computed(() => Math.max(0, props.collaborators.length - props.maxDisplay))
</script>

<style scoped>
.collaborators {
  display: flex;
  align-items: center;
}
.collaborators .el-avatar {
  border: 2px solid #fff;
  margin-left: -8px;
  cursor: pointer;
}
.collaborators .el-avatar:first-child {
  margin-left: 0;
}
.extra-count {
  background: #e8e8e8;
  color: #666;
  font-size: 12px;
}
</style>
