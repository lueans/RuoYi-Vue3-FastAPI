import test from 'node:test'
import assert from 'node:assert/strict'
import { getMindmapAiPendingCharacterCount, getMindmapAiPlaybackPacing } from '../mindmap-ai-playback-pacing.js'
import { nextMindmapAiDraftFrame } from '../mindmap-ai-live-preview.js'

const node = (uid, text, children = [], extra = {}) => ({ data: { uid, text, ...extra }, children })

test('新目标到达时估算单个长节点剩余字数，不将其误当作短节点', () => {
  const current = { root: node('root', '已展示') }
  const target = { root: node('root', '已展示' + '字'.repeat(2000)) }
  const pendingCharacters = getMindmapAiPendingCharacterCount(current, target)
  assert.equal(pendingCharacters, 2000)
  assert.equal(getMindmapAiPlaybackPacing({ pendingCharacters, pendingNodes: 1 }).delayMs, 0)
})

test('字数估算按共同前缀和完整字素计算，并覆盖多个节点及空文字操作', () => {
  const current = { root: node('root', '根', [node('old', '旧文字'), node('unchanged', '保留')]) }
  const target = { root: node('root', '根', [
    node('old', '👨‍👩‍👧‍👦e\u0301👍🏽'), node('unchanged', '保留'), node('empty', ''),
    node('new', '新增'),
  ]) }
  assert.equal(getMindmapAiPendingCharacterCount(current, target), 6)
  assert.equal(getMindmapAiPendingCharacterCount(target, target), 0)
  assert.equal(getMindmapAiPendingCharacterCount(null, { root: node('root', '甲乙丙') }), 3)
})

test('缩短文字和仅样式修改至少保留一次帧预算，数据键顺序不构成修改', () => {
  assert.equal(getMindmapAiPendingCharacterCount(
    { root: node('root', '甲乙丙') }, { root: node('root', '甲') },
  ), 1)
  assert.equal(getMindmapAiPendingCharacterCount(
    { root: node('root', '甲') }, { root: node('root', '甲', [], { color: 'red' }) },
  ), 1)
  assert.equal(getMindmapAiPendingCharacterCount(
    { root: node('root', '甲') }, { root: { data: { text: '甲', uid: 'root' }, children: [] } },
  ), 0)
})

test('低积压保留原有逐字节奏，调度器只决定延迟', () => {
  assert.deepEqual(getMindmapAiPlaybackPacing({ pendingCharacters: 10 }), { delayMs: 56 })
  assert.deepEqual(getMindmapAiPlaybackPacing({ pendingNodes: 1 }), { delayMs: 56 })
})

test('播放积压增大时加快节奏，不能增大字符预算或直出完整节点', () => {
  let previousDelay = 56
  for (const pendingCharacters of [10, 60, 100, 500, 1000, 10000]) {
    const pacing = getMindmapAiPlaybackPacing({ pendingCharacters })
    assert(pacing.delayMs <= previousDelay)
    assert(pacing.delayMs >= 0)
    previousDelay = pacing.delayMs
  }
  assert.equal(previousDelay, 0)
  assert(getMindmapAiPlaybackPacing({ pendingNodes: 500 }).delayMs < 56)
})

test('持续未排空的队列和终态队列会追赶，但不改变单字输出约束', () => {
  const fresh = getMindmapAiPlaybackPacing({ pendingCharacters: 40, now: 10000, oldestPendingAt: 10000 })
  const aged = getMindmapAiPlaybackPacing({ pendingCharacters: 40, now: 10000, oldestPendingAt: 0 })
  const terminal = getMindmapAiPlaybackPacing({ pendingCharacters: 40, terminal: true })
  assert(aged.delayMs < fresh.delayMs)
  assert(terminal.delayMs < fresh.delayMs)
})

test('无效估计、倒退时钟不会生成负数或无限定时器', () => {
  for (const input of [
    {}, { pendingCharacters: NaN, pendingNodes: Infinity },
    { pendingCharacters: -100, pendingNodes: -3, now: 5, oldestPendingAt: 10 },
    { pendingCharacters: 1, now: NaN, oldestPendingAt: Infinity },
  ]) {
    const pacing = getMindmapAiPlaybackPacing(input)
    assert(Number.isFinite(pacing.delayMs))
    assert(pacing.delayMs >= 0 && pacing.delayMs <= 56)
  }
})

test('高积压速度策略下首帧仍是首字，且一个节点完成后才开始下一个', () => {
  const node = (uid, text, children = []) => ({ data: { uid, text }, children })
  let current = { root: node('root', '根') }
  const target = { root: node('root', '根', [node('first', '甲乙丙'), node('second', '丁戊')]) }
  const observed = []
  for (let index = 0; index < 10; index++) {
    const pacing = getMindmapAiPlaybackPacing({ pendingNodes: 500, terminal: true })
    assert(pacing.delayMs < 56)
    const frame = nextMindmapAiDraftFrame(current, target)
    observed.push([frame.change.uid, frame.change.text])
    current = frame.document
    if (!frame.remaining) break
  }
  assert.deepEqual(observed, [['first', '甲'], ['first', '甲乙'], ['first', '甲乙丙'], ['second', '丁'], ['second', '丁戊']])
  assert.deepEqual(current, target)
})
