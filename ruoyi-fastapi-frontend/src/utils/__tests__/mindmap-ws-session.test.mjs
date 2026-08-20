import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const backendEndpointUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/websocket/mindmap_ws.py',
  import.meta.url,
)
const backendAuthUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/websocket/ws_auth.py',
  import.meta.url,
)
const backendRoomUrl = new URL(
  '../../../../ruoyi-fastapi-backend/module_mindmap/websocket/room_manager.py',
  import.meta.url,
)
const yjsSourceUrl = new URL('../yjs-sync.js', import.meta.url)
const editorSourceUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const pageSourceUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)

test('协作心跳复核登录会话并禁止失效连接断开回写', async () => {
  const [endpointSource, authSource, roomSource] = await Promise.all([
    readFile(backendEndpointUrl, 'utf8'),
    readFile(backendAuthUrl, 'utf8'),
    readFile(backendRoomUrl, 'utf8'),
  ])

  assert.match(endpointSource, /await validate_ws_token\(auth_token, redis\)/)
  assert.match(endpointSource, /RECHECK_TRANSIENT_FAILURE_LIMIT = 3/)
  assert.match(endpointSource, /room_manager\.block_disconnect_persistence\(websocket\)/)
  assert.match(endpointSource, /'type': 'session_ended'/)
  assert.match(endpointSource, /return auth_payload, WS_RETRY_LATER_CLOSE_CODE/)
  assert.match(endpointSource, /code='access_check_unavailable'/)
  assert.match(authSource, /code='session_revoked'/)
  assert.match(authSource, /code='auth_unavailable'/)
  assert.match(roomSource, /def block_disconnect_persistence\(self, websocket: WebSocket\)/)
})

test('会话终止事件贯穿 Yjs、编辑器草稿保护和页面反馈', async () => {
  const [yjsSource, editorSource, pageSource] = await Promise.all([
    readFile(yjsSourceUrl, 'utf8'),
    readFile(editorSourceUrl, 'utf8'),
    readFile(pageSourceUrl, 'utf8'),
  ])

  assert.match(yjsSource, /session_ended: \(data\) => this\._handleSessionEnded\(data\)/)
  assert.match(yjsSource, /_terminateCollaboration\(data, 'session-ended', 'onSessionEnded'\)/)
  assert.match(editorSource, /terminateEditingSession\('session-ended', data\)/)
  assert.match(editorSource, /localDraftPreserved = saveMindmapDraftFallbackSync/)
  assert.match(editorSource, /localBackupCreated = downloadConflictBackup\(fullData, `mindmap-\$\{eventName\}`\)/)
  assert.match(pageSource, /@session-ended="onSessionEnded"/)
  assert.match(pageSource, /登录会话已失效/)
  assert.match(pageSource, /协作认证暂时不可用/)
})

test('损坏协作缓存恢复状态保持可用并以警告样式呈现', async () => {
  const [yjsSource, pageSource] = await Promise.all([
    readFile(yjsSourceUrl, 'utf8'),
    readFile(pageSourceUrl, 'utf8'),
  ])

  assert.match(yjsSource, /connectionState\.value = 'degraded'/)
  assert.match(yjsSource, /invalidSources/)
  assert.match(pageSource, /degraded: '协作已恢复'/)
  assert.match(pageSource, /realtimeState\.value === 'connected'/)
  assert.match(pageSource, /'degraded'\]\.includes\(realtimeState\.value\)/)
})
