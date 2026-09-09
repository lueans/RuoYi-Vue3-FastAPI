import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import {
  getMindmapPresenceInitial,
  MINDMAP_PRESENCE_PANEL_LIMIT,
  normalizeMindmapPresenceDisplayLimit,
  normalizeMindmapPresenceUsers,
} from '../mindmap-presence.js'

const componentSourceUrl = new URL('../../components/MindMap/Collaborators.vue', import.meta.url)
const pageSourceUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)

test('在线成员规范化拒绝非法身份、去重并清理展示字段', () => {
  const users = normalizeMindmapPresenceUsers([
    { id: 7, name: '  Alice\nAdmin  ', avatar: 'javascript:alert(1)', color: 'red' },
    { id: '7', name: '重复连接' },
    { userId: 'member-8', nickName: ' 小 王 ', avatar: '/profile/avatar.png', color: '#123AbC' },
    { id: Number.NaN, name: '非法数字' },
    { id: '', name: '空身份' },
    null,
  ])

  assert.equal(users.length, 2)
  assert.deepEqual(users[0], {
    id: 7,
    identity: '7',
    name: 'Alice Admin',
    avatar: '',
    color: normalizeMindmapPresenceUsers([{ id: 7 }])[0].color,
  })
  assert.deepEqual(users[1], {
    id: 'member-8',
    identity: 'member-8',
    name: '小 王',
    avatar: '/profile/avatar.png',
    color: '#123AbC',
  })
})

test('在线成员头像颜色、显示上限和 Unicode 首字符保持稳定', () => {
  const first = normalizeMindmapPresenceUsers([{ id: 'same-user', name: '张三' }])[0]
  const second = normalizeMindmapPresenceUsers([{ id: 'same-user', name: '改名后' }])[0]

  assert.equal(first.color, second.color)
  assert.equal(getMindmapPresenceInitial(' 张三'), '张')
  assert.equal(getMindmapPresenceInitial('alice'), 'A')
  assert.equal(getMindmapPresenceInitial(''), '?')
  assert.equal(normalizeMindmapPresenceDisplayLimit(-3), 1)
  assert.equal(normalizeMindmapPresenceDisplayLimit(99), 8)
  assert.equal(normalizeMindmapPresenceDisplayLimit('4'), 5)
  assert.equal(MINDMAP_PRESENCE_PANEL_LIMIT, 100)
})

test('在线成员组件提供键盘入口、完整名单和有界溢出反馈', async () => {
  const [component, page] = await Promise.all([
    readFile(componentSourceUrl, 'utf8'),
    readFile(pageSourceUrl, 'utf8'),
  ])

  assert.match(component, /<div v-if="onlineUsers\.length > 0" class="collaborators">\s*<el-popover/)
  assert.match(component, /<button[\s\S]*type="button"[\s\S]*class="presence-trigger"/)
  assert.match(component, /:aria-label="`\$\{onlineUsers\.length\} 位协作者在线，查看成员名单`"/)
  assert.match(component, /aria-haspopup="dialog"/)
  assert.match(component, /:aria-expanded="popoverVisible"/)
  assert.match(component, /role="dialog"[\s\S]*tabindex="-1"/)
  assert.match(component, /@show="handlePopoverShow"/)
  assert.match(component, /@keydown\.esc\.stop\.prevent="handlePopoverEscape"/)
  assert.match(component, /panelRef\.value\?\.focus\?\.\(\)/)
  assert.match(component, /triggerRef\.value\?\.focus\?\.\(\)/)
  assert.match(component, /aria-label="在线协作者名单"/)
  assert.match(component, /panelOverflowCount/)
  assert.match(component, /class="extra-count mobile-extra-count"[\s\S]*?onlineUsers\.length - 1/)
  assert.match(component, /@media \(max-width: 760px\)[\s\S]*?\.mobile-extra-count[\s\S]*?display: inline-flex[\s\S]*?position: absolute/)
  assert.equal(/v-for="user in collaborators"/.test(component), false)
  assert.match(page, /:dark="isDark"/)

  const headerActions = page.match(/class="header-actions"[\s\S]*?<div class="header-utility-group"/)?.[0] || ''
  assert.match(headerActions, /<Collaborators[\s\S]*?:max-display="5"[\s\S]*?class="header-collaborators"/)
  assert.match(headerActions, /has-recovery-actions/)
  assert.ok(
    headerActions.indexOf('<Collaborators') < headerActions.indexOf('share-btn'),
    '在线协作者入口应位于分享按钮左侧',
  )
  assert.doesNotMatch(page.match(/<div class="header-left">[\s\S]*?<div[\s\S]*?class="header-command-center"/)?.[0] || '', /<Collaborators/)
  assert.doesNotMatch(page, /\.document-meta,\s*\.header-collaborators,\s*\.history-action-btn/)
  assert.match(headerActions, /class="header-icon-btn share-btn"[\s\S]*?<span class="header-action-label">分享<\/span>/)
  assert.doesNotMatch(page, /\n\s*\.share-btn\s*\{/)
  assert.match(page, /@media \(max-width: 480px\)[\s\S]*?\.brand-mark[\s\S]*?display: none/)
  assert.match(page, /\.header-actions\.has-recovery-actions[\s\S]*?\.filter-action-btn,[\s\S]*?\.comment-action-btn[\s\S]*?display: none/)
})
