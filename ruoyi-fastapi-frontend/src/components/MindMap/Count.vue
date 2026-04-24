<template>
  <div class="countContainer" :class="{ isDark: isDark }">
    <div class="item">
      <span class="name">字数</span>
      <span class="value">{{ words }}</span>
    </div>
    <div class="item">
      <span class="name">节点</span>
      <span class="value">{{ num }}</span>
    </div>
  </div>
</template>

<script setup>
import bus from './useEventBus'
import { store } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)

const words = ref(0)
const num = ref(0)
let textStr = ''
const countEl = document.createElement('div')

function onDataChange(data) {
  textStr = ''
  words.value = 0
  num.value = 0
  walk(data)
  countEl.textContent = textStr.replace(/<[^>]*>/g, '')
  words.value = countEl.textContent.length
}

function walk(data) {
  if (!data) return
  num.value++
  textStr += String(data.data?.text) || ''
  if (data.children && data.children.length > 0) {
    data.children.forEach(item => {
      walk(item)
    })
  }
}

onMounted(() => {
  bus.on('data_change', onDataChange)
  if (props.mindMap) {
    onDataChange(props.mindMap.getData())
  }
})

watch(() => props.mindMap, (mm) => {
  if (mm) {
    onDataChange(mm.getData())
  }
})

onBeforeUnmount(() => {
  bus.off('data_change', onDataChange)
})
</script>

<style lang="less" scoped>
.countContainer {
  padding: 0 12px;
  position: fixed;
  left: 20px;
  bottom: 20px;
  background: hsla(0, 0%, 100%, 0.8);
  border-radius: 2px;
  opacity: 0.8;
  height: 22px;
  line-height: 22px;
  font-size: 12px;
  display: flex;

  &.isDark {
    background: #262a2e;

    .item {
      color: hsla(0, 0%, 100%, 0.6);
    }
  }

  .item {
    color: #555;
    margin-right: 15px;

    &:last-of-type {
      margin-right: 0;
    }

    .name {
      margin-right: 5px;
    }
  }
}

@media screen and (max-width: 900px) {
  .countContainer {
    display: none;
  }
}
</style>
