import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMindmapListRouteQuery,
  decodeMindmapListReturnState,
  encodeMindmapListReturnState,
  isSameMindmapListRouteQuery,
  isSameMindmapListState,
  parseMindmapListRouteQuery,
} from '../mindmap-list-route.js'

test('列表路由状态规范化全部筛选、分页和确定性排序', () => {
  const state = parseMindmapListRouteQuery({
    q: '  季度目标  ',
    status: 'all',
    folder: '12',
    tag: '8',
    page: '3',
    size: '20',
    sort: 'name-asc',
  })

  assert.deepEqual(state, {
    scope: 'owned',
    keyword: '季度目标',
    status: null,
    folderId: 12,
    tagId: 8,
    pageNum: 3,
    pageSize: 20,
    sortKey: 'name-asc',
  })
  assert.deepEqual(buildMindmapListRouteQuery(state), {
    sort: 'name-asc',
    q: '季度目标',
    status: 'all',
    folder: '12',
    tag: '8',
    page: '3',
    size: '20',
  })
})

test('共享与回收站拒绝无效目录标签状态和越界参数', () => {
  const shared = parseMindmapListRouteQuery({
    scope: 'shared', folder: '3', tag: '4', page: '-1', size: '101', sort: '__proto__',
  }, 'created-desc')
  assert.deepEqual(shared, {
    scope: 'shared',
    keyword: '',
    status: 0,
    folderId: null,
    tagId: null,
    pageNum: 1,
    pageSize: 10,
    sortKey: 'created-desc',
  })

  const trash = parseMindmapListRouteQuery({ scope: 'trash', status: '1', folder: '2' })
  assert.equal(trash.status, null)
  assert.equal(trash.folderId, null)
  assert.deepEqual(buildMindmapListRouteQuery(trash), {
    sort: 'updated-desc',
    scope: 'trash',
  })
})

test('查询比较忽略未知参数但识别任一产品状态变化', () => {
  assert.equal(
    isSameMindmapListRouteQuery(
      { sort: 'updated-desc', unknown: 'keep-out' },
      { sort: 'updated-desc' },
    ),
    true,
  )
  const original = parseMindmapListRouteQuery({ q: '目标', page: '2' })
  assert.equal(isSameMindmapListState(original, { ...original }), true)
  assert.equal(isSameMindmapListState(original, { ...original, pageNum: 3 }), false)
})

test('返回状态令牌安全往返并拒绝损坏、非规范与超长输入', () => {
  const original = parseMindmapListRouteQuery({
    scope: 'shared', q: '复盘', status: '1', page: '2', sort: 'name-desc',
  })
  const encoded = encodeMindmapListReturnState(original)
  assert.deepEqual(decodeMindmapListReturnState(encoded), original)
  assert.equal(decodeMindmapListReturnState('{broken'), null)
  assert.equal(decodeMindmapListReturnState('[]'), null)
  assert.equal(decodeMindmapListReturnState('{}'), null)
  assert.equal(decodeMindmapListReturnState('{"sort":"updated-desc","page":"01"}'), null)
  assert.equal(decodeMindmapListReturnState('{"sort":"updated-desc","unknown":"value"}'), null)
  assert.equal(decodeMindmapListReturnState('x'.repeat(513)), null)
})

test('关键词拒绝控制字符并按 Unicode 字符截断', () => {
  assert.equal(parseMindmapListRouteQuery({ q: '目标\n范围' }).keyword, '')
  assert.equal(Array.from(parseMindmapListRouteQuery({ q: '脑'.repeat(101) }).keyword).length, 100)
})
