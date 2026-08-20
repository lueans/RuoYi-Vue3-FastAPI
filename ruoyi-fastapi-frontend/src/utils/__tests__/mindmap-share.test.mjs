import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  copyMindmapShareText,
  isFutureMindmapShareExpiry,
  resolveMindmapShareStatus,
} from '../mindmap-share.js'

const NOW = Date.parse('2026-08-18T00:00:00.000Z')

test('分享状态区分有效、已过期和已禁用链接', () => {
  assert.equal(resolveMindmapShareStatus({ isActive: 1 }, NOW).key, 'active')
  assert.equal(resolveMindmapShareStatus({
    isActive: 1,
    expireTime: '2026-08-17T23:59:59.000Z',
  }, NOW).key, 'expired')
  assert.equal(resolveMindmapShareStatus({
    isActive: 0,
    expireTime: '2026-08-19T00:00:00.000Z',
  }, NOW).key, 'disabled')
})

test('异常过期时间不可被当作有效分享', () => {
  const status = resolveMindmapShareStatus({ isActive: 1, expireTime: 'not-a-date' }, NOW)

  assert.equal(status.key, 'invalid')
  assert.equal(status.usable, false)
})

test('自定义有效期必须严格晚于当前时间', () => {
  assert.equal(isFutureMindmapShareExpiry('2026-08-18T00:00:01.000Z', NOW), true)
  assert.equal(isFutureMindmapShareExpiry('2026-08-18T00:00:00.000Z', NOW), false)
  assert.equal(isFutureMindmapShareExpiry(null, NOW), false)
})

function createCopyDocument(copyResult) {
  let focusCount = 0
  const textarea = {
    style: {},
    setAttribute() {},
    select() {},
    remove() {},
    value: '',
  }
  return {
    documentRef: {
      activeElement: { focus: () => { focusCount += 1 } },
      body: { appendChild() {} },
      createElement: () => textarea,
      execCommand: () => copyResult,
    },
    focusCount: () => focusCount,
  }
}

test('分享复制优先使用 Clipboard API', async () => {
  let copied = ''
  const result = await copyMindmapShareText('https://example.com/share', {
    clipboard: { writeText: async value => { copied = value } },
  })

  assert.equal(result, true)
  assert.equal(copied, 'https://example.com/share')
})

test('Clipboard 被拒绝时降级复制并恢复原焦点', async () => {
  const fallback = createCopyDocument(true)
  const result = await copyMindmapShareText('https://example.com/share', {
    clipboard: { writeText: async () => { throw new Error('denied') } },
    documentRef: fallback.documentRef,
  })

  assert.equal(result, true)
  assert.equal(fallback.focusCount(), 1)
})

test('降级复制返回失败时不会伪报成功', async () => {
  const fallback = createCopyDocument(false)
  await assert.rejects(
    copyMindmapShareText('https://example.com/share', {
      clipboard: null,
      documentRef: fallback.documentRef,
    }),
    /复制失败/
  )
})

test('分享弹窗具备加载竞态、操作锁、禁用确认和完整表单可访问名称', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/ShareDialog.vue', import.meta.url),
    'utf8'
  )

  assert.match(source, /const listRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /const dialogSession = createScopedAsyncSession\(\)/)
  assert.match(source, /const session = dialogSession\.activate\(mindmapId\)/)
  assert.match(source, /dialogSession\.isCurrent\(session\)/)
  assert.match(source, /getMindmapId\(\) === session\.identity/)
  assert.match(source, /getShareLinks\(session\.identity\)/)
  assert.match(source, /listRequests\.isCurrent\(requestId\)/)
  assert.match(source, /import \{[^}]*onBeforeUnmount[^}]*\} from 'vue'/)
  assert.match(source, /onBeforeUnmount\(invalidateShareSession\)/)
  assert.match(source, /role="alert"/)
  assert.match(source, /@click="reloadLinks">重新加载/)
  assert.match(source, /function reloadLinks\(\) \{[\s\S]*void loadLinks\(\)/)
  assert.match(source, /ElMessageBox\.confirm\([\s\S]*禁用后该链接将立即无法访问/)
  assert.match(source, /aria-label="分享访问权限"/)
  assert.match(source, /aria-label="分享链接有效期"/)
  assert.match(source, /aria-label="分享链接过期时间"/)
  assert.match(source, /aria-label="复制分享链接"/)
  assert.match(source, /copyMindmapShareText\(url\)/)
  assert.match(source, /encodeURIComponent\(String\(token \|\| ''\)\)/)
})

test('分享写操作绑定打开时文件会话并在切换或关闭后停止反馈', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/ShareDialog.vue', import.meta.url),
    'utf8'
  )

  assert.match(source, /mindmapId: session\.identity/)
  assert.equal((source.match(/if \(!isShareSessionCurrent\(session\)\) return/g) || []).length >= 5, true)
  assert.match(source, /operationType\.value = `confirm-disable:\$\{linkId\}`[\s\S]*ElMessageBox\.confirm/)
  assert.match(source, /await deleteShareLink\(linkId\)[\s\S]*if \(!isShareSessionCurrent\(session\)\) return/)
  assert.match(source, /watch\(\(\) => props\.mindmapId,[\s\S]*invalidateShareSession\(\)[\s\S]*visible\.value = false/)
  assert.match(source, /width="min\(560px, calc\(100vw - 32px\)\)"/)
  assert.match(source, /@media \(max-width: 600px\)[\s\S]*flex-direction: column/)
})
