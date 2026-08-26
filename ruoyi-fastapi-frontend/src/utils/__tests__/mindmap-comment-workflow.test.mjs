import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createCommentMutationTracker } from '../mindmap-comment-mutation.js'

async function readSource(relativePath) {
  return readFile(new URL(relativePath, import.meta.url), 'utf8')
}

test('评论入口、右侧侧栏和实时变更形成完整工作流', async () => {
  const [page, editor, sidebar, sync] = await Promise.all([
    readSource('../../views/mindmap/edit.vue'),
    readSource('../../components/MindMap/Edit.vue'),
    readSource('../../components/MindMap/CommentSidebar.vue'),
    readSource('../yjs-sync.js'),
  ])

  assert.match(page, /class="header-icon-btn comment-action-btn"/)
  assert.match(page, /@click="openComments"/)
  assert.match(editor, /<CommentSidebar v-if="mindMap && props\.mindmapId"/)
  assert.match(editor, /bus\.emit\('comment_changed', data\)/)
  assert.match(sync, /comment_changed: \(data\) => this\.options\.onCommentChanged\?\.\(data\)/)
  assert.match(sidebar, /scope-tabs/)
  assert.match(sidebar, /当前节点/)
  assert.match(sidebar, /updateMindmapCommentStatus/)
  assert.match(sidebar, /replyMindmapComment/)
  assert.match(sidebar, /deleteMindmapComment/)
  assert.match(sidebar, /setInterval[\s\S]*15000/)
  assert.match(sidebar, /> span \{ color: #a2a7ae;/)
  assert.match(sidebar, /button \{[\s\S]{0,300}color: #fff;/)
  assert.match(sidebar, /button \{[\s\S]{0,200}justify-content: center;/)
  assert.doesNotMatch(sidebar, /\.composer-actions span,/)
})

test('节点评论数量是运行时装饰，不写入脑图节点内容', async () => {
  const [node, commentNode, sidebar] = await Promise.all([
    readSource('../../libs/simple-mind-map/src/core/render/node/MindMapNode.js'),
    readSource('../../libs/simple-mind-map/src/core/render/node/nodeComment.js'),
    readSource('../../components/MindMap/CommentSidebar.vue'),
  ])

  assert.match(node, /this\.commentCount = 0/)
  assert.match(commentNode, /function setCommentCount\(count\)/)
  assert.match(commentNode, /this\.mindMap\.emit\('node_comment_click', this, event\)/)
  assert.doesNotMatch(commentNode, /setData|setNodeData|execCommand/)
  assert.match(sidebar, /findNodeByUid\?\.\(uid\)\?\.setCommentCount\?\.\(0\)/)
  assert.match(sidebar, /node\?\.setCommentCount\?\.\(count\)/)
})

test('评论请求具备竞态保护、分页和卸载清理', async () => {
  const sidebar = await readSource('../../components/MindMap/CommentSidebar.vue')

  assert.match(sidebar, /createLatestRequestTracker/)
  assert.match(sidebar, /requestTracker\.isCurrent\(requestId\)/)
  assert.match(sidebar, /threads\.value = append \? mergeThreads\(threads\.value, nextRows\) : nextRows/)
  assert.match(sidebar, /if \(!loaded && pageNum\.value === previousPage \+ 1\) pageNum\.value = previousPage/)
  assert.match(sidebar, /requestTracker\.invalidate\(\)/)
  assert.match(sidebar, /off\?\.\('node_comment_click', onNodeCommentClick\)/)
  assert.match(sidebar, /stopPolling\(\)/)
})

test('点击评论卡片定位节点并隐藏原节点主题按钮', async () => {
  const sidebar = await readSource('../../components/MindMap/CommentSidebar.vue')

  assert.match(sidebar, /@click="onThreadCardClick\(thread, \$event\)"/)
  assert.match(sidebar, /@keydown\.enter\.self\.prevent="focusThreadFromCard\(thread\)"/)
  assert.match(sidebar, /@keydown\.space\.self\.prevent="focusThreadFromCard\(thread\)"/)
  assert.match(sidebar, /function focusThreadFromCard\(thread\)[\s\S]*focusNode\(thread\.nodeUid\)/)
  assert.match(sidebar, /target\.closest\(threadInteractiveSelector\)/)
  assert.match(sidebar, /selection && !selection\.isCollapsed/)
  assert.match(sidebar, /function setCommentTarget\(node, \{ focus = false \} = \{\}\)/)
  assert.match(sidebar, /props\.mindMap\?\.opt\?\.readonly[\s\S]*smm-node-comment-target/)
  assert.match(sidebar, /on\?\.\('node_click', onCanvasNodeClick\)/)
  assert.match(sidebar, /off\?\.\('node_click', onCanvasNodeClick\)/)
  assert.match(sidebar, /function onNodeCommentClick\(node\)[\s\S]*setCommentTarget\(node, \{ focus: true \}\)/)
  assert.doesNotMatch(sidebar, /class="thread-node"/)
})

test('评论写入重试复用同一幂等键，意图变化后生成新键', () => {
  let sequence = 0
  const tracker = createCommentMutationTracker({ createKey: () => `comment-key-${++sequence}-123456` })

  const first = tracker.begin('thread:5:node-1', 'node-1\u0000第一版')
  const retry = tracker.begin('thread:5:node-1', 'node-1\u0000第一版')
  const edited = tracker.begin('thread:5:node-1', 'node-1\u0000第二版')

  assert.equal(retry.key, first.key)
  assert.notEqual(edited.key, first.key)
  tracker.succeed('thread:5:node-1', edited.key)
  assert.notEqual(tracker.begin('thread:5:node-1', 'node-1\u0000第二版').key, edited.key)
})

test('评论发布、回复和错误恢复具备完整客户端保护', async () => {
  const [sidebar, api] = await Promise.all([
    readSource('../../components/MindMap/CommentSidebar.vue'),
    readSource('../../api/mindmap/comment.js'),
  ])

  assert.match(api, /headers: \{ 'Idempotency-Key': idempotencyKey \}/)
  assert.match(sidebar, /const newCommentDrafts = reactive\(\{\}\)/)
  assert.match(sidebar, /const newCommentErrors = reactive\(\{\}\)/)
  assert.match(sidebar, /const creatingNodeUids = reactive\(new Set\(\)\)/)
  assert.match(sidebar, /const lastSelectedNode = shallowRef\(null\)/)
  assert.match(sidebar, /store\.activeSidebar === 'comments' \? lastSelectedNode\.value : null/)
  assert.match(sidebar, /const replyingThreadIds = reactive\(new Set\(\)\)/)
  assert.match(sidebar, /const statusUpdatingThreadIds = reactive\(new Set\(\)\)/)
  assert.match(sidebar, /草稿已保留/)
  assert.match(sidebar, /refreshAfterMutation/)
  assert.doesNotMatch(sidebar, /const submitting = ref/)
})
