import test from 'node:test'
import assert from 'node:assert/strict'
import {
  compareMindmapAiPreviewCoordinates,
  countMindmapAiDraftNodes,
  describeMindmapAiDraftChange,
  nextMindmapAiDraftFrame,
  summarizeMindmapAiDraftChanges,
} from '../mindmap-ai-live-preview.js'

const node = (uid, text, children = []) => ({ data: { uid, text }, children })

function drainFrames(current, target, limit = 2000) {
  const frames = []
  for (let index = 0; index < limit; index++) {
    const frame = nextMindmapAiDraftFrame(current, target)
    frames.push(frame)
    current = frame.document
    if (!frame.remaining) return frames
  }
  assert.fail('planner did not converge')
}

test('多个已存在节点同时改名时，尚未轮到的节点必须保留原文', () => {
  const before = { root: node('root', '根', [node('a', '原节点甲'), node('b', '原节点乙')]) }
  const target = { root: node('root', '根', [node('a', '甲更新'), node('b', '乙更新')]) }
  let current = before
  for (const text of ['甲', '甲更', '甲更新']) {
    const frame = nextMindmapAiDraftFrame(current, target)
    assert.equal(frame.document.root.children[0].data.text, text)
    assert.equal(frame.document.root.children[1].data.text, '原节点乙')
    assert.equal(frame.typewriterTarget.text, '甲更新')
    current = frame.document
  }
  const next = nextMindmapAiDraftFrame(current, target)
  assert.equal(next.document.root.children[1].data.text, '乙')
})

test('长旧文替换为短新文仍从首字开始，追加文字从共同前缀继续', () => {
  const frame = nextMindmapAiDraftFrame(
    { root: node('root', '这是很长的旧文字') },
    { root: node('root', '新文字') },
  )
  assert.equal(frame.document.root.data.text, '新')
  const append = nextMindmapAiDraftFrame(frame.document, { root: node('root', '新文字追加') })
  assert.equal(append.document.root.data.text, '新文')
})

test('移动删除与新增混合时也不能直接展示整个目标树', () => {
  const before = { root: node('root', '根', [node('a', '甲'), node('b', '乙'), node('deleted', '删除')]) }
  const target = { root: node('root', '根', [node('b', '乙'), node('a', '甲'), node('c', '新节点'), node('d', '另一个节点')]) }
  let frame = nextMindmapAiDraftFrame(before, target)
  assert.equal(frame.document.root.children.find(n => n.data.uid === 'c').data.text, '新')
  assert.equal(frame.change.uid, 'c', 'focus the typing node, not a simultaneous deletion')
  assert.equal(frame.document.root.children.some(n => n.data.uid === 'd'), false)
  for (let count = 0; frame.remaining && count < 30; count++) {
    frame = nextMindmapAiDraftFrame(frame.document, target)
  }
  assert.equal(frame.remaining, 0)
  assert.deepEqual(frame.document, target)
})

test('新父节点尚未播放时，移入它的原有子树保持可见且不重新打字', () => {
  const existing = node('a', '原有重要节点', [node('child', '原有子节点')])
  const before = { root: node('root', '旧根', [existing, node('b', '保留顺序')]) }
  const target = { root: node('root', '新根', [
    node('new-parent', '新增父节点', [existing]), node('b', '保留顺序'),
  ]) }
  const visit = root => [root, ...root.children.flatMap(visit)]
  let current = before
  const played = []
  for (let count = 0; count < 30; count++) {
    const frame = nextMindmapAiDraftFrame(current, target)
    const nodes = visit(frame.document.root)
    assert.equal(nodes.filter(n => n.data.uid === 'a').length, 1, 'existing subtree is never lost or duplicated')
    assert.equal(nodes.find(n => n.data.uid === 'a'), existing, 'unchanged subtree identity is retained')
    assert.equal(nodes.find(n => n.data.uid === 'child').data.text, '原有子节点')
    played.push(frame.change.uid)
    if (frame.change.uid === 'root') {
      assert.deepEqual(frame.document.root.children.map(n => n.data.uid), ['a', 'b'])
    } else {
      assert.equal(frame.document.root.children[0].children[0], existing)
    }
    current = frame.document
    if (!frame.remaining) break
  }
  assert.deepEqual(new Set(played), new Set(['root', 'new-parent']))
  assert.deepEqual(current, target)
})

test('移入新父节点前保留将被删除的旧容器，依赖满足时原子移动并删除旧容器', () => {
  const existing = node('a', '不可闪烁')
  let current = { root: node('root', '旧根', [node('old-parent', '待删除容器', [existing])]) }
  const target = { root: node('root', '新根', [node('new-parent', '新容器', [existing])]) }
  for (let count = 0; count < 20; count++) {
    const frame = nextMindmapAiDraftFrame(current, target)
    const parent = frame.document.root.children[0]
    assert.equal(parent.children[0], existing)
    assert.equal(parent.data.uid, frame.change.uid === 'root' ? 'old-parent' : 'new-parent')
    assert.notEqual(frame.change.uid, 'a')
    current = frame.document
    if (!frame.remaining) break
  }
  assert.deepEqual(current, target)
})

test('新父依赖按完整祖先链判断，祖先子孙互换不会形成中间循环或丢节点', () => {
  const before = { root: node('root', '旧根', [node('a', '节点甲', [node('b', '节点乙')])]) }
  const target = { root: node('root', '新根', [node('new-parent', '新容器', [node('b', '节点乙', [node('a', '节点甲')])])]) }
  let current = before
  for (let count = 0; count < 20; count++) {
    const frame = nextMindmapAiDraftFrame(current, target)
    assert.equal(countMindmapAiDraftNodes(frame.document.root), frame.change.uid === 'root' ? 3 : 4)
    assert.notEqual(frame.change.uid, 'a')
    assert.notEqual(frame.change.uid, 'b')
    current = frame.document
    if (!frame.remaining) break
  }
  assert.deepEqual(current, target)
})

test('移走一个兄弟不会把留在原父下的节点误报为重排，聚焦实际移动节点', () => {
  const child = node('a', '被移动节点')
  const before = { root: node('root', '根', [child, node('parent', '折叠父节点')]) }
  const target = { root: node('root', '根', [node('parent', '折叠父节点', [child])]) }
  const frame = nextMindmapAiDraftFrame(before, target)
  assert.deepEqual(frame.change, { kind: 'move', uid: 'a', text: '被移动节点' })
  assert.equal(summarizeMindmapAiDraftChanges(before.root, target.root).moved, 1)
  assert.deepEqual(frame.document, target)
})

test('草稿坐标按生成世代优先、世代内按操作游标单调比较', () => {
  assert.equal(compareMindmapAiPreviewCoordinates(
    { epoch: 2, version: 1 },
    { epoch: 1, version: 99 },
  ), 1)
  assert.equal(compareMindmapAiPreviewCoordinates(
    { epoch: 2, version: 4 },
    { epoch: 2, version: 5 },
  ), -1)
  assert.equal(compareMindmapAiPreviewCoordinates(
    { epoch: 2, version: 5 },
    { epoch: 2, version: 5 },
  ), 0)
})



test('相同脑图根节点只推进游标，不要求渲染器重复绘制', () => {
  const document = { layout: 'logicalStructure', root: node('root', '根') }
  const frame = nextMindmapAiDraftFrame(document, structuredClone(document))
  assert.equal(frame.rootUnchanged, true)
  assert.equal(frame.remaining, 0)
})


test('元数据变化不能绕过逐节点逐字播放并提前暴露完整云端树', () => {
  const before = {
    layout: 'logicalStructure',
    theme: { template: 'classic' },
    root: node('root', '根'),
  }
  const after = {
    layout: 'mindMap',
    theme: { template: 'dark' },
    root: node('root', '根', [
      node('a', '第一个节点'),
      node('b', '第二个节点'),
    ]),
  }
  const frame = nextMindmapAiDraftFrame(before, after)
  assert.equal(frame.document.layout, 'logicalStructure')
  assert.deepEqual(frame.document.theme, { template: 'classic' })
  assert.equal(frame.document.root.children.length, 1)
  assert.equal(frame.document.root.children[0].data.uid, 'a')
  assert.equal(frame.document.root.children[0].data.text, '第')
  assert.ok(frame.remaining > 0)
})

test('仅元数据变化时播放器保持当前展示树并交由终态原子提交', () => {
  const before = {
    layout: 'logicalStructure',
    root: node('root', '根', [node('a', '现有节点')]),
  }
  const after = {
    layout: 'mindMap',
    root: structuredClone(before.root),
  }
  const frame = nextMindmapAiDraftFrame(before, after)
  assert.equal(frame.rootUnchanged, true)
  assert.equal(frame.document, before)
})

test('脑图元数据键顺序变化不会触发重复画布重绘', () => {
  const before = {
    layout: 'logicalStructure',
    theme: { template: 'classic', root: { color: '#333' } },
    documentData: { showWatermark: false, padding: 12 },
    root: node('root', '根'),
  }
  const sameValuesDifferentKeyOrder = {
    layout: 'logicalStructure',
    theme: { root: { color: '#333' }, template: 'classic' },
    documentData: { padding: 12, showWatermark: false },
    root: node('root', '根'),
  }
  const frame = nextMindmapAiDraftFrame(before, sameValuesDifferentKeyOrder)
  assert.equal(frame.rootUnchanged, true)
  assert.equal(frame.document, before)
})

test('统计脑图草稿节点数时忽略无效节点并支持深层分支', () => {
  const root = node('root', '根', [
    node('a', '分支', [node('a1', '子项')]),
    { data: {}, children: [node('ignored-child', '不应计入')] },
  ])
  assert.equal(countMindmapAiDraftNodes(root), 3)
})

test('汇总脑图草稿的新增、修改、移动和删除数量', () => {
  const before = node('root', '根', [
    node('a', '原内容'),
    node('b', '待移动'),
    node('deleted', '待删除'),
  ])
  const after = node('root', '根', [
    node('b', '待移动'),
    node('a', '新内容'),
    node('added', '新增'),
  ])
  assert.deepEqual(summarizeMindmapAiDraftChanges(before, after), {
    added: 1,
    updated: 1,
    moved: 2,
    deleted: 1,
    total: 5,
  })
})

test('节点数据键顺序变化不会被误报为修改', () => {
  const before = node('root', '根')
  before.data.style = { color: '#333', fontSize: 14 }
  const after = node('root', '根')
  after.data.style = { fontSize: 14, color: '#333' }
  assert.deepEqual(summarizeMindmapAiDraftChanges(before, after), {
    added: 0,
    updated: 0,
    moved: 0,
    deleted: 0,
    total: 0,
  })
  assert.equal(describeMindmapAiDraftChange(before, after), null)
})

test('运行时瞬时字段不计入修改，也不生成无内容变化的播放帧', () => {
  for (const field of ['isActive', 'inserting', 'needUpdate', 'resetRichText', 'activeStyle']) {
    for (const [beforeValue, afterValue] of [[false, undefined], [undefined, true], [false, true]]) {
      const before = { root: node('root', '根') }
      const after = { root: node('root', '根') }
      if (beforeValue !== undefined) before.root.data[field] = beforeValue
      if (afterValue !== undefined) after.root.data[field] = afterValue
      const originalBefore = structuredClone(before)
      const originalAfter = structuredClone(after)
      assert.deepEqual(summarizeMindmapAiDraftChanges(before.root, after.root), {
        added: 0, updated: 0, moved: 0, deleted: 0, total: 0,
      }, field)
      assert.equal(describeMindmapAiDraftChange(before.root, after.root), null, field)
      const frame = nextMindmapAiDraftFrame(before, after)
      assert.equal(frame.rootUnchanged, true, field)
      assert.equal(frame.document, before, field)
      assert.equal(frame.remaining, 0, field)
      assert.deepEqual(before, originalBefore, 'comparison does not mutate the runtime baseline')
      assert.deepEqual(after, originalAfter, 'comparison does not mutate the cloud target')
    }
  }
})

test('忽略瞬时字段时仍检测业务字段新增、修改、删除和嵌套属性', () => {
  const fields = {
    text: ['原文', '新文'],
    note: ['原备注', '新备注'],
    expand: [true, false],
    richText: [false, true],
    tag: [[{ tagId: 1 }], [{ tagId: 2 }]],
    customLeft: [10, 20],
    style: [{ activeStyle: 'old' }, { activeStyle: 'new' }],
    customBusinessData: [{ value: 1 }, { value: 2 }],
  }
  for (const [field, values] of Object.entries(fields)) {
    for (const [beforeValue, afterValue] of [[undefined, values[0]], values, [values[1], undefined]]) {
      const before = node('root', '根')
      const after = node('root', '根')
      before.data.isActive = false
      if (beforeValue === undefined) delete before.data[field]
      else before.data[field] = beforeValue
      if (afterValue === undefined) delete after.data[field]
      else after.data[field] = afterValue
      assert.equal(summarizeMindmapAiDraftChanges(before, after).updated, 1, field)
      assert.equal(describeMindmapAiDraftChange(before, after)?.kind, 'update', field)
    }
  }
})

test('运行时基线带 isActive 时直接从真实新增节点首字开始，保持逐节点流式', () => {
  const before = { root: node('root', '根', [node('old', '原有节点')]) }
  before.root.data.isActive = false
  before.root.children[0].data.isActive = false
  const target = { root: node('root', '根', [
    node('old', '原有节点'), node('first', '第一项'), node('second', '第二项'),
  ]) }
  assert.deepEqual(summarizeMindmapAiDraftChanges(before.root, target.root), {
    added: 2, updated: 0, moved: 0, deleted: 0, total: 2,
  })
  let current = before
  for (const [uid, text] of [
    ['first', '第'], ['first', '第一'], ['first', '第一项'],
    ['second', '第'], ['second', '第二'], ['second', '第二项'],
  ]) {
    const frame = nextMindmapAiDraftFrame(current, target)
    assert.equal(frame.change.uid, uid)
    assert.equal(frame.document.root.children.find(child => child.data.uid === uid).data.text, text)
    assert.equal(frame.document.root.children[0], before.root.children[0])
    if (uid === 'first') assert.equal(frame.document.root.children.some(child => child.data.uid === 'second'), false)
    current = frame.document
  }
  assert.equal(summarizeMindmapAiDraftChanges(current.root, target.root).total, 0)
  assert.equal(nextMindmapAiDraftFrame(current, target).rootUnchanged, true)
})

test('合法 UID 包含分隔符时仍识别兄弟重排并播放结构变化', () => {
  const before = { root: node('root', '根', [node('a', '甲'), node('a|a', '乙')]) }
  const after = { root: node('root', '根', [node('a|a', '乙'), node('a', '甲')]) }
  assert.deepEqual(summarizeMindmapAiDraftChanges(before.root, after.root), {
    added: 0, updated: 0, moved: 2, deleted: 0, total: 2,
  })
  const frame = nextMindmapAiDraftFrame(before, after)
  assert.notEqual(frame.rootUnchanged, true)
  assert.deepEqual(frame.change, { kind: 'move', uid: 'a|a', text: '乙' })
  assert.deepEqual(frame.document, after)
  assert.equal(frame.remaining, 0)
})

test('逐帧新增节点时聚焦最新节点', () => {
  const before = node('root', '根', [node('a', '已有')])
  const after = node('root', '根', [node('a', '已有'), node('b', '新用例')])
  assert.deepEqual(describeMindmapAiDraftChange(before, after), {
    kind: 'add', uid: 'b', text: '新用例',
  })
})

test('单帧批量新增多个节点时聚焦先序遍历中首个变更节点', () => {
  const before = node('root', '根', [node('a', '分支甲'), node('b', '分支乙')])
  const after = node('root', '根', [
    node('a', '分支甲', [node('a1-1', '甲的子项')]),
    node('b', '分支乙', [node('b1', '乙的子项')]),
  ])
  assert.deepEqual(describeMindmapAiDraftChange(before, after), {
    kind: 'add', uid: 'a1-1', text: '甲的子项',
  })
})

test('逐帧修改节点内容时聚焦该节点', () => {
  const before = node('root', '根', [node('a', '原用例')])
  const after = node('root', '根', [node('a', '修改后的用例')])
  assert.deepEqual(describeMindmapAiDraftChange(before, after), {
    kind: 'update', uid: 'a', text: '修改后的用例',
  })
})

test('删除子树时提示删除并聚焦仍存在的父节点', () => {
  const before = node('root', '根', [node('a', '被删除', [node('child', '子项')]), node('b', '保留')])
  const after = node('root', '根', [node('b', '保留')])
  assert.deepEqual(describeMindmapAiDraftChange(before, after), {
    kind: 'delete', uid: 'root', text: '被删除',
  })
})

test('相同帧不会虚报编辑步骤', () => {
  const before = node('root', '根', [node('a', '已有')])
  assert.equal(describeMindmapAiDraftChange(before, structuredClone(before)), null)
})

test('批量新增节点逐帧出现在正确分支和顺序，最终等于服务端草稿', () => {
  const initial = { root: node('root', '根', [node('existing', '已有')]) }
  const target = { root: node('root', '根', [
    node('branch', '新分支', [node('first', '第一条'), node('second', '第二条')]),
    node('existing', '已有'),
    node('last', '最后一条'),
  ]) }
  let current = initial
  const frames = drainFrames(current, target)
  current = frames.at(-1).document
  assert.deepEqual([...new Set(frames.map(frame => frame.change.uid))], ['branch', 'first', 'second', 'last'])
  assert.equal(frames[0].change.text, '新')
  assert.equal(frames[0].document.root.children[0].children.length, 0)
  assert.equal(frames.at(-1).remaining, 0)
  assert.deepEqual(current, target)
  assert.deepEqual(initial.root.children.map(child => child.data.uid), ['existing'])
})

test('逐帧结果聚焦当前节点，并严格遵守先序节点顺序', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', [node('a', '甲'), node('b', '乙')]) }
  const frame = nextMindmapAiDraftFrame(initial, target)
  assert.deepEqual(frame.change, { kind: 'add', uid: 'a', text: '甲' })
  const lastFrame = nextMindmapAiDraftFrame(frame.document, target)
  assert.deepEqual(lastFrame.change, { kind: 'add', uid: 'b', text: '乙' })
})

test('流式预览按节点顺序逐字揭示节点文本', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', [node('a', '你好'), node('b', '世界')]) }
  let current = initial
  const frames = []
  for (let index = 0; index < 8; index += 1) {
    const frame = nextMindmapAiDraftFrame(current, target)
    frames.push(frame.document.root.children.map(item => item.data.text))
    current = frame.document
    if (!frame.remaining) break
  }
  assert.deepEqual(frames, [['你'], ['你好'], ['你好', '世'], ['你好', '世界']])
  assert.deepEqual(current, target)
})

test('流式预览不会拆坏 emoji 等 Unicode 代理对', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', [node('a', '🚀AI')]) }
  const first = nextMindmapAiDraftFrame(initial, target)
  assert.equal(first.document.root.children[0].data.text, '🚀')
  assert.deepEqual(first.typewriterTarget, { uid: 'a', text: '🚀AI' })
  const second = nextMindmapAiDraftFrame(first.document, target)
  assert.equal(second.document.root.children[0].data.text, '🚀A')
})

test('逐字播放以完整字素为单位，不拆散家庭 emoji 和组合字符', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', [node('a', '👨‍👩‍👧‍👦é完成')]) }
  const first = nextMindmapAiDraftFrame(initial, target)
  assert.equal(first.document.root.children[0].data.text, '👨‍👩‍👧‍👦')
  const second = nextMindmapAiDraftFrame(first.document, target)
  assert.equal(second.document.root.children[0].data.text, '👨‍👩‍👧‍👦é')
})

test('大批量节点始终逐个逐字显示，最终完整收敛', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', Array.from({ length: 100 }, (_, index) => (
    node(`n${index}`, `节点 ${index}`)
  ))) }
  const frames = drainFrames(initial, target)
  assert.equal(frames.length, target.root.children.reduce((sum, child) => sum + Array.from(child.data.text).length, 0))
  let previousCount = 0
  for (const frame of frames) {
    const shown = frame.document.root.children
    assert(shown.length - previousCount <= 1)
    for (let index = 0; index < shown.length - 1; index++) {
      assert.deepEqual(shown[index], target.root.children[index])
    }
    previousCount = shown.length
  }
  assert.deepEqual(frames.at(-1).document, target)
})

test('大批量服务端目标首帧只出现第一个节点的首字', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', Array.from({ length: 50 }, (_, index) => (
    node(`smooth-${index}`, `节点 ${index}`)
  ))) }
  const frame = nextMindmapAiDraftFrame(initial, target)
  assert.equal(frame.remaining, 50)
  assert.equal(frame.nodeCount, 2)
  assert.deepEqual(frame.document.root.children.map(child => child.data.text), ['节'])
})

test('终态权威目标也保持逐字播放，不提前展示完整节点', () => {
  const initial = { root: node('root', '根') }
  const target = { root: node('root', '根', [node('finished', '最终完整正文')]) }
  const frames = drainFrames(initial, target)
  assert.deepEqual(frames.map(frame => frame.change.text), ['最', '最终', '最终完', '最终完整', '最终完整正', '最终完整正文'])
  assert.deepEqual(frames.at(-1).document, target)
})

test('逐帧更新不会改变深层节点属性和子树结构', () => {
  const initial = { root: node('root', '根', [
    node('branch', '分支', [node('leaf', '旧内容')]),
  ]) }
  const target = { root: node('root', '根', [
    node('branch', '分支', [node('leaf', '新内容'), node('new-leaf', '新增内容')]),
  ]) }
  let current = initial
  const frames = []
  let remaining = 1
  while (remaining > 0 || frames.length === 0) {
    const next = nextMindmapAiDraftFrame(current, target)
    frames.push(next)
    current = next.document
    remaining = next.remaining
    if (frames.length > 10) throw new Error('深层节点帧未能收敛')
  }
  assert.deepEqual(current, target)
  assert.equal(frames.at(-1).nodeCount, 4)
})

test('逐帧只复制变更路径并保留未变更子树引用', () => {
  const untouched = node('untouched', '未变更', [node('leaf', '叶子')])
  const initial = { root: node('root', '根', [
    untouched,
    node('changed', '旧内容'),
  ]) }
  const target = { root: node('root', '根', [
    node('untouched', '未变更', [node('leaf', '叶子')]),
    node('changed', '新内容'),
  ]) }

  const frame = nextMindmapAiDraftFrame(initial, target)

  assert.notEqual(frame.document.root, initial.root)
  assert.equal(frame.document.root.children[0], untouched)
  assert.notEqual(frame.document.root.children[1], initial.root.children[1])
  assert.equal(initial.root.children[1].data.text, '旧内容')
})

test('生成中收到更新草稿时，从已展示节点继续而不回闪旧版本', () => {
  const initial = { root: node('root', '根') }
  const firstTarget = { root: node('root', '根', [node('a', '甲'), node('b', '乙')]) }
  const latestTarget = { root: node('root', '根', [
    node('a', '甲'), node('b', '乙'), node('c', '丙'), node('d', '丁'),
  ]) }
  const firstFrame = nextMindmapAiDraftFrame(initial, firstTarget).document
  assert.deepEqual(firstFrame.root.children.map(child => child.data.uid), ['a'])
  const nextFrame = nextMindmapAiDraftFrame(firstFrame, latestTarget).document
  assert.deepEqual(nextFrame.root.children.map(child => child.data.uid), ['a', 'b'])
})

test('混合修改移动删除都维持逐字输出，结构变更不会直出新增全文', () => {
  const initial = { root: node('root', '根', [node('a', '已有'), node('b', '保留')]) }
  const edited = { root: node('root', '根', [node('a', '修改'), node('b', '保留'), node('c', '新增')]) }
  const moved = { root: node('root', '根', [node('b', '保留'), node('a', '已有'), node('c', '新增')]) }
  const deleted = { root: node('root', '根', [node('b', '保留'), node('c', '新增')]) }
  const editFrames = drainFrames(initial, edited)
  assert.deepEqual(editFrames.map(frame => frame.change.text), ['修', '修改', '新', '新增'])
  assert.equal(editFrames[0].nodeCount, 3)
  assert.deepEqual(editFrames[0].document.root.children.map(child => child.data.uid), ['a', 'b'])
  for (const target of [moved, deleted]) {
    const frames = drainFrames(initial, target)
    assert.equal(frames[0].change.text, '新')
    assert.equal(frames[0].remaining, 1)
    assert.deepEqual(frames[0].document.root.children.map(child => child.data.uid), target.root.children.map(child => child.data.uid))
    assert.deepEqual(frames.at(-1).document, target)
  }
})
