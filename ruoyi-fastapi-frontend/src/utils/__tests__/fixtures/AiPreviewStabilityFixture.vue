<template>
  <main>
    <h1>AI 旧图编辑稳定性验收</h1>
    <p>独立测试画布 · 使用生产播放器、SVG 渲染器和镜头控制 · 不连接后端或 Agent</p>
    <nav>
      <button :disabled="!ready || playing" @click="play">模拟再次 AI 编辑</button>
      <button :disabled="!ready" :aria-pressed="following" @click="camera.setFollowing(!following)">{{ following ? '暂停跟随 AI' : '跟随 AI 变更' }}</button>
      <button :disabled="!ready" @click="map.view.translateXY(0, 100)">模拟手动平移</button>
      <button :disabled="!ready || playing" @click="checkRichText">验证富文本改写</button>
    </nav>
    <p role="status">{{ status }}</p>
    <div ref="canvas" class="canvas" aria-label="独立流式脑图画布" tabindex="0"
      @pointerdown.capture="camera.pause()" @wheel.capture.passive="camera.pause()" @keydown.capture="camera.pause()"></div>
    <pre aria-label="验收结果">{{ report }}</pre>
  </main>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import MindMap from '@mind-map'
import { nextMindmapAiDraftFrame } from '../../mindmap-ai-live-preview.js'
import { applyMindmapAiPresentationFrame, clearMindmapAiPresentation } from '../../mindmap-ai-presentation.js'
import { createMindmapAiCamera } from '../../mindmap-ai-camera.js'
import { nextRevealedText } from '../../../libs/simple-mind-map/src/utils/textReveal.js'
const canvas = ref(null), ready = ref(false), playing = ref(false), following = ref(false)
const status = ref('正在初始化'), report = ref('')
let map, session = { jobId: 'fixture-0' }, round = 0, alive = true, viewChanges = 0, observer
const camera = createMindmapAiCamera({ getMindmap: () => map, getSession: () => session,
  onFollowingChange: value => { following.value = value } })
const node = (uid, text, children = []) => ({ data: { uid, text }, children })
const initial = { root: node('root', '已有登录功能测试脑图', Array.from({ length: 12 }, (_, i) =>
  node(`branch-${i}`, `原有测试分支 ${i + 1}`, Array.from({ length: 3 }, (_, j) => node(`leaf-${i}-${j}`, `保留原有场景 ${i + 1}-${j + 1}`))))) }
async function play() {
  if (playing.value) return
  playing.value = true
  camera.reset()
  session = { jobId: `fixture-${++round}` }
  viewChanges = 0
  const before = { root: map.getData() }, target = structuredClone(before)
  const replacement = `使用有效手机号及验证码完成登录（第 ${round} 轮）`
  target.root.children[0].data.text = replacement
  target.root.children[10].data.text = `重新整理已有边界测试（第 ${round} 轮）`
  target.root.children[0].children.push(node(`new-${round}`, '本轮新增验证码失效分支'))
  const prefixes = [], replacements = [], frames = []
  let current = before
  try {
    for (let i = 0; i < 300 && alive; i++) {
      const frame = nextMindmapAiDraftFrame(current, target)
      if (frame.rootUnchanged) break
      await applyMindmapAiPresentationFrame(map, current, frame)
      if (!alive) return
      current = frame.document
      camera.focus({ jobId: session.jobId, nodeUids: [frame.change.uid], focusKey: `${session.jobId}:${i}` })
      if (frame.change.uid === 'branch-0') replacements.push(frame.change.text)
      if (frame.change.uid === `new-${round}`) prefixes.push(frame.change.text)
      frames.push(frame.change.uid)
      status.value = `第 ${round} 轮 · 第 ${frames.length} 帧 · ${following.value ? '跟随中' : '固定视角'} · ${frame.change.text}`
      await new Promise(resolve => setTimeout(resolve, 110))
      if (!frame.remaining) break
    }
    await clearMindmapAiPresentation(map)
    report.value = JSON.stringify({ round, complete: JSON.stringify(current) === JSON.stringify(target),
      frames: frames.length, viewChanges, replacements, prefixes,
      untouchedBranchPreserved: JSON.stringify(current.root.children[5]) === JSON.stringify(before.root.children[5]),
      zoom: map.view.getTransformData().state.scale }, null, 2)
    status.value = `第 ${round} 轮已完成 · 视角变化 ${viewChanges} 次`
  } catch (error) { status.value = `失败：${error.message}` }
  finally { playing.value = false }
}
function checkRichText() {
  const replacement = nextRevealedText('<p><b>已有完整文字</b></p>', '<p><i>新的完整说明</i></p>', true, true)
  const append = nextRevealedText('<p>保留</p>', '<p>保留新增</p>', true, true)
  report.value = JSON.stringify({ richReplacement: replacement, richAppend: append,
    passed: replacement === '<p><i>新的完整说明</i></p>' && append === '<p>保留新</p>' }, null, 2)
}
onMounted(() => {
  map = new MindMap({ el: canvas.value, data: structuredClone(initial.root), readonly: true, layout: 'logicalStructure', theme: 'default' })
  map.renderAsync(() => { ready.value = true; status.value = '49 个已有节点已就绪，可以模拟连续两轮编辑' })
  map.on('view_data_change', () => { if (playing.value) viewChanges++ })
  observer = new ResizeObserver(() => { if (canvas.value?.clientWidth && canvas.value?.clientHeight) map.resize() })
  observer.observe(canvas.value)
})
onBeforeUnmount(() => { alive = false; camera.dispose(); observer?.disconnect(); map?.destroy() })
</script>
<style scoped>
:global(body) { margin: 0; font-family: system-ui, sans-serif; background: #f4f5f7; color: #202020; }
main { padding: 16px; }
h1 { font-size: 18px; }
p, button { font-size: 13px; }
nav { display: flex; gap: 8px; flex-wrap: wrap; }
button { min-height: 36px; padding: 6px 12px; border: 1px solid #ccc; border-radius: 6px; background: white; }
button[aria-pressed='true'] { color: #5643bd; border-color: currentColor; }
.canvas { height: 500px; overflow: hidden; background: white; border: 1px solid #ddd; }
pre { white-space: pre-wrap; font-size: 12px; }
</style>
