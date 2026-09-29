import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { createNoticeHarness, noticeTemplate, noticeStyles } from './fixtures/live-preview-notice-harness.mjs'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')

test('逐帧绘制忙闲变化不切换提示文案，也不触发紧急读屏播报', () => {
  const s = createNoticeHarness(source, Vue)
  const titles = new Set(), descriptions = new Set()
  for (let i = 0; i < 40; i++) {
    s.livePreviewRendering.value = i % 2 === 0
    titles.add(s.livePreviewNoticeTitle.value)
    descriptions.add(s.livePreviewNoticeDescription.value)
  }
  assert.equal(titles.size, 1)
  assert.equal(descriptions.size, 1)
})

test('运行中追赶/追平交替不增删一整句提示', () => {
  const s = createNoticeHarness(source, Vue)
  s.latestPreviewVersion.value = s.livePreviewRenderedVersion.value
  const descriptions = new Set()
  for (const pending of [true, false, true, false]) {
    s.livePreviewFramesPending.value = pending
    descriptions.add(s.livePreviewNoticeDescription.value)
  }
  assert.equal(descriptions.size, 1)
})

test('每帧渲染不禁用暂停按钮，提示圆点不持续闪烁', () => {
  assert.doesNotMatch(noticeTemplate(source), /:disabled="livePreviewRendering"/)
  assert.doesNotMatch(noticeStyles(source), /animation:\s*aiPulse/)
})

test('真实阶段变化仍准确展示暂停、断线、保存和尾帧追赶', () => {
  const s = createNoticeHarness(source, Vue)
  s.livePreviewPaused.value = true
  assert.match(s.livePreviewNoticeTitle.value, /已暂停/)
  s.livePreviewPaused.value = false
  s.realtimeConnectionState.value = 'offline'
  assert.match(s.livePreviewNoticeTitle.value, /中断/)
  s.realtimeConnectionState.value = 'connected'
  s.running.value = false
  assert.match(s.livePreviewNoticeTitle.value, /正在完成/)
  s.livePreviewRendering.value = true
  assert.match(s.livePreviewNoticeTitle.value, /正在完成/)
  s.livePreviewAutoAccepting.value = true
  assert.match(s.livePreviewNoticeTitle.value, /正在保存/)
  s.livePreviewAutoAccepting.value = false
  s.livePreviewAutoAcceptFailedJobId.value = 'notice-job'
  assert.match(s.livePreviewNoticeTitle.value, /保存未完成/)
})

test('状态稳定不冻结真实节点与变更进度，也不提前宣称保存成功', () => {
  const s = createNoticeHarness(source, Vue)
  s.livePreviewRenderedNodeCount.value = 50
  s.livePreviewChangeSummary.value = { added: 6, updated: 4 }
  assert.match(s.livePreviewNoticeDescription.value, /50 个节点/)
  assert.match(s.livePreviewNoticeDescription.value, /新增 6.*修改 4/)
  assert.doesNotMatch(s.livePreviewNoticeDescription.value, /已保存|保存成功/)
})
