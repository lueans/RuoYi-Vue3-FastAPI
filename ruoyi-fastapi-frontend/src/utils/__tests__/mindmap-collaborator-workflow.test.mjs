import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getCollaboratorErrorMessage,
  isCollaboratorPermissionDowngrade,
  normalizeCollaboratorSearchKeyword,
} from '../mindmap-collaborator.js'
import { createLatestRequestTracker, isElementDialogDismissal } from '../mindmap-async.js'

test('协作者搜索关键字会清理空白并限制接口长度', () => {
  assert.equal(normalizeCollaboratorSearchKeyword('  年糕  '), '年糕')
  assert.equal(normalizeCollaboratorSearchKeyword('x'.repeat(80)).length, 64)
})

test('仅编辑权限降为查看权限时触发危险确认', () => {
  assert.equal(isCollaboratorPermissionDowngrade(1, 0), true)
  assert.equal(isCollaboratorPermissionDowngrade(0, 1), false)
  assert.equal(isCollaboratorPermissionDowngrade(0, 0), false)
})

test('请求跟踪器拒绝已失效的列表或搜索响应', () => {
  const tracker = createLatestRequestTracker()
  const first = tracker.begin()
  const second = tracker.begin()

  assert.equal(tracker.isCurrent(first), false)
  assert.equal(tracker.isCurrent(second), true)
  tracker.invalidate()
  assert.equal(tracker.isCurrent(second), false)
})

test('弹窗取消和关闭不会被当作接口异常', () => {
  assert.equal(isElementDialogDismissal('cancel'), true)
  assert.equal(isElementDialogDismissal('close'), true)
  assert.equal(isElementDialogDismissal(new Error('network')), false)
})

test('协作者错误优先展示后端业务消息', () => {
  assert.equal(
    getCollaboratorErrorMessage({ response: { data: { msg: '该用户已是协作者' } } }, '失败'),
    '该用户已是协作者',
  )
})

test('协作者管理具备竞态保护、操作锁、撤权确认和失败恢复', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/CollaboratorManager.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /createLatestRequestTracker/)
  assert.match(source, /const managerSession = createScopedAsyncSession\(\)/)
  assert.match(source, /managerSession\.activate\(mindmapId\)/)
  assert.match(source, /managerSession\.isCurrent\(session\)/)
  assert.match(source, /Number\(props\.mindmapId\) === session\.identity/)
  assert.match(source, /listRequests\.isCurrent\(requestId\)/)
  assert.match(source, /searchRequests\.isCurrent\(requestId\)/)
  assert.match(source, /const isOperating = computed/)
  assert.match(source, /当前编辑会话会立即结束/)
  assert.match(source, /当前会话也会结束/)
  assert.match(source, /role="alert"/)
  assert.match(source, /重新加载/)
  assert.match(source, /searchUsers\(session\.identity, normalizedKeyword\)/)
  assert.match(source, /mindmapId: session\.identity/)
  assert.match(source, /if \(!isManagerActive\(session\)\) return/)
  assert.match(source, /operationType\.value = `confirm-permission:\$\{collaboratorId\}`/)
  assert.match(source, /operationType\.value = `confirm-remove:\$\{collaboratorId\}`/)
  assert.doesNotMatch(source, /item\.permission = newPermission/)
  assert.match(source, /\? \{ \.\.\.collaborator, permission \}/)
  assert.match(source, /label-position="top"/)
  assert.match(source, /class="collaboratorControl"/)
  assert.match(source, /\.collaboratorControl,[\s\S]*\.addButton[\s\S]*width: 100%/)
})

test('只有脑图所有者会看到协作者管理入口', async () => {
  const [storeSource, triggerSource, editorSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/useStore.js', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/SidebarTrigger.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
  ])

  assert.match(storeSource, /canManageCollaborators: false/)
  assert.match(storeSource, /setCanManageCollaborators/)
  assert.match(triggerSource, /item\.value !== 'collaboratorManager'/)
  assert.match(editorSource, /actions\.setCanManageCollaborators\(data\.isOwner === true\)/)
})
