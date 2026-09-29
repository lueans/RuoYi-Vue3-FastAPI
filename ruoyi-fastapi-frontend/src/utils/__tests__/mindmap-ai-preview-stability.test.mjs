import test from 'node:test'
import assert from 'node:assert/strict'
import { nextMindmapAiDraftFrame } from '../mindmap-ai-live-preview.js'
import { getMindmapAiPendingCharacterCount } from '../mindmap-ai-playback-pacing.js'

const node = (uid, text, children = []) => ({ data: { uid, text }, children })
test('再次编辑已有脑图：改写和缩短文字不先清空旧正文再重新打字', () => {
  for (const [oldText, newText] of [
    ['正确手机号加正确验证码登录成功', '使用有效手机号及验证码完成登录'],
    ['登录错误提示需要包含错误原因', '登录失败'],
    ['已有文字', ''],
  ]) {
    const untouched = node('b', '原有分支必须保留')
    const before = { root: node('root', '已有脑图', [node('a', oldText), untouched]) }
    const target = { root: node('root', '已有脑图', [node('a', newText), untouched]) }
    const frame = nextMindmapAiDraftFrame(before, target)
    assert.equal(frame.document.root.children[0].data.text, newText)
    assert.equal(frame.document.root.children[1], untouched)
    assert.equal(frame.remaining, 0)
    assert.equal(before.root.children[0].data.text, oldText)
  }
})

test('保留流式预览：新增及末尾追加继续按完整字素逐字出现', () => {
  const before = { root: node('root', '已有脑图', [node('a', '登录')]) }
  const target = { root: node('root', '已有脑图', [node('a', '登录成功'), node('b', '新增分支')]) }
  const outputs = []
  let current = before
  for (let i = 0; i < 20; i++) {
    const frame = nextMindmapAiDraftFrame(current, target)
    outputs.push([frame.change.uid, frame.change.text])
    current = frame.document
    if (!frame.remaining) break
  }
  assert.deepEqual(outputs, [['a', '登录成'], ['a', '登录成功'], ['b', '新'], ['b', '新增'], ['b', '新增分'], ['b', '新增分支']])
  assert.deepEqual(current, target)
})

test('更换仍在播放的目标时不倒退到共同前缀，随后仍可流式追加', () => {
  const before = { root: node('root', '已展示的旧内容') }
  const replacement = { root: node('root', '已展示的新内容') }
  const replaced = nextMindmapAiDraftFrame(before, replacement)
  assert.deepEqual(replaced.document, replacement)
  assert.equal(getMindmapAiPendingCharacterCount(before, replacement), 1)
  const appended = nextMindmapAiDraftFrame(replaced.document, { root: node('root', '已展示的新内容补充') })
  assert.equal(appended.document.root.data.text, '已展示的新内容补')
})
