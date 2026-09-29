<template>
  <main>
    <h1>liveDraftNotice 闪烁回归</h1>
    <p>复用生产提示框模板、状态计算与样式；模拟逐帧 ACK，不调用 Agent、不修改业务脑图。</p>
    <button :disabled="replaying" @click="replay">回放 20 帧</button>
    <label>面板宽度<select v-model.number="width"><option :value="340">340px</option><option :value="420">420px</option><option :value="520">520px</option></select></label>
    <div ref="viewport" class="fixtureViewport" :style="{ width: `${width}px` }">
      <article v-for="i in 4" :key="i"><strong>历史编辑 · 第 {{ i }} 轮</strong><p>已保留之前的编辑内容和对话，本轮继续完善异常与边界场景。</p></article>
      <Notice />
    </div>
    <pre aria-label="帧回放测量">{{ report }}</pre>
  </main>
</template>
<script setup>
import * as Vue from 'vue'
import { compile } from 'vue/dist/vue.esm-bundler.js'
import source from '../../../components/MindMap/MindmapAiDialog.vue?raw'
import { createNoticeHarness, noticeStyles, noticeTemplate } from './live-preview-notice-harness.mjs'
const { ref, defineComponent, h, nextTick, onBeforeUnmount } = Vue
const s = createNoticeHarness(source, Vue)
const width = ref(420), viewport = ref(null), replaying = ref(false), report = ref('点击回放，对比绘制前后标题、按钮和高度。')
const render = compile(noticeTemplate(source))
const NoticeBody = defineComponent({ setup: () => ({ ...s, livePreviewNoticeRef: ref(null), toggleLivePreviewPlayback: () => { s.livePreviewPaused.value = !s.livePreviewPaused.value } }), render })
const Notice = () => h('div', [h('style', noticeStyles(source)), h(NoticeBody)])
let alive = true
onBeforeUnmount(() => { alive = false })
async function replay() {
  replaying.value = true
  const samples = []
  let firstElement, replacements = 0
  for (let i = 0; i < 40 && alive; i++) {
    s.livePreviewRendering.value = i % 2 === 0
    await nextTick()
    await new Promise(resolve => requestAnimationFrame(resolve))
    if (!alive) break
    const el = viewport.value.querySelector('.liveDraftNotice')
    if (firstElement && firstElement !== el) replacements++
    firstElement = el
    // Same bottom-follow behavior as a chat receiving live audit messages.
    viewport.value.scrollTop = viewport.value.scrollHeight
    samples.push({ title: el.querySelector('strong').textContent, height: el.getBoundingClientRect().height,
      disabled: el.querySelector('button').disabled, scroll: viewport.value.scrollTop,
      dotAnimation: getComputedStyle(el.querySelector('i')).animationName })
    await new Promise(resolve => setTimeout(resolve, 60))
  }
  if (!alive) return
  const transitions = key => samples.slice(1).filter((item, i) => item[key] !== samples[i][key]).length
  report.value = JSON.stringify({ samples: samples.length, titleChanges: transitions('title'), heightChanges: transitions('height'),
    buttonChanges: transitions('disabled'), scrollChanges: transitions('scroll'), replacements,
    heights: [...new Set(samples.map(item => item.height))], dotAnimation: samples[0]?.dotAnimation }, null, 2)
  replaying.value = false
}
</script>
<style scoped>
main { margin:24px; font:14px/1.6 system-ui,sans-serif; } h1 { font-size:20px; }
label { margin-left:12px; } button,select { min-height:32px; }
.fixtureViewport { max-width:100%; height:360px; overflow:auto; margin-top:16px; padding:14px 18px; box-sizing:border-box; border:1px solid #ddd;
  --ai-ink:#202020; --ai-muted:#737373; --ai-live-border:#ded5fd; --ai-live-bg:#faf8ff; --ai-live-dot:#7657f6; }
article { margin-bottom:24px; padding:10px; background:#f6f6f6; } article p { margin:8px 0; }
pre { white-space:pre-wrap; }
</style>
