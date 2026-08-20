import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createLoginRedirectLocation,
  normalizeLoginRedirect,
  resolvePostLoginLocation,
} from '../login-redirect.js'

test('登录路由把完整目标地址作为单个 redirect 查询值交给路由器编码', () => {
  assert.deepEqual(
    createLoginRedirectLocation('/mindmap/edit?id=122&readonly=1'),
    {
      path: '/login',
      query: { redirect: '/mindmap/edit?id=122&readonly=1' },
    },
  )
})
test('登录成功后恢复目标路径、查询参数和锚点', () => {
  assert.equal(
    resolvePostLoginLocation({
      redirect: '/mindmap/edit?id=122&readonly=1#node-a',
    }),
    '/mindmap/edit?id=122&readonly=1#node-a',
  )
})

test('兼容旧链接中被拆成登录页查询参数的脑图 ID', () => {
  assert.equal(
    resolvePostLoginLocation({ redirect: '/mindmap/edit', id: '122' }),
    '/mindmap/edit?id=122',
  )
})

test('完整 redirect 中已有的参数优先于旧链接的重复参数', () => {
  assert.equal(
    resolvePostLoginLocation({ redirect: '/mindmap/edit?id=122', id: '999' }),
    '/mindmap/edit?id=122',
  )
})

test('拒绝外部、协议相对、反斜线和超长登录目标', () => {
  assert.equal(normalizeLoginRedirect('https://example.com/steal'), '/')
  assert.equal(normalizeLoginRedirect('//example.com/steal'), '/')
  assert.equal(normalizeLoginRedirect('/\\example.com/steal'), '/')
  assert.equal(normalizeLoginRedirect(`/${'x'.repeat(5000)}`), '/')
})
