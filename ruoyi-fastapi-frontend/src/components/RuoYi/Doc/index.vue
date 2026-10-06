<template>
  <button type="button" class="productHelpButton" aria-label="脑图使用帮助，在新标签页打开" @click="goto">
    <svg-icon icon-class="question" aria-hidden="true" />
  </button>
</template>

<script setup>
const router = useRouter()

function goto() {
  window.open(router.resolve('/help/mindmap').href, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.productHelpButton { border: 0; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.productHelpButton:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
</style>
