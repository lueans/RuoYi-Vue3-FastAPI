<template>
  <Sidebar ref="sidebarRef" title="快捷键" placement="left" open-on-mount>
    <div class="box" :class="{ isDark: isDark }">
      <div v-for="item in shortcutKeyList" :key="item.type">
        <div class="title">{{ item.type }}</div>
        <div class="list" v-for="item2 in item.list" :key="item2.value">
          <div class="item">
            <span
              v-if="item2.icon"
              class="icon iconfont"
              :class="[item2.icon]"
            ></span>
            <span class="name" :title="item2.name">{{ item2.name }}</span>
            <div class="value" :title="item2.value">{{ item2.value }}</div>
          </div>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store } from './useStore'
import { shortcutKeyList } from './config'

const sidebarRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)

watch(() => store.activeSidebar, (val) => {
  if (val === 'shortcutKey') {
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.box {
  padding: 4px 16px 16px;

  &.isDark {
    .title {
      color: #e5e6eb;
    }

    .list {
      .item {
        .icon {
          color: hsla(0, 0%, 100%, 0.5);
        }
        .name {
          color: hsla(0, 0%, 100%, 0.7);
        }
        .value {
          color: hsla(0, 0%, 100%, 0.35);
        }
      }
    }
  }

  .title {
    font-size: 12px;
    font-weight: 600;
    color: #8f959e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin: 20px 0 12px;
    &:first-child { margin-top: 8px; }
  }

  .list {
    font-size: 13px;

    .item {
      display: flex;
      align-items: center;
      padding: 6px 0;

      .icon {
        font-size: 15px;
        margin-right: 10px;
        color: #8f959e;
      }

      .name {
        color: #1f2329;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .value {
        color: #8f959e;
        margin-left: auto;
        white-space: nowrap;
        font-size: 12px;
        padding-left: 12px;
      }
    }
  }
}
</style>
