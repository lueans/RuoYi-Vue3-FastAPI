import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { replaceAllLiteralText } from '../../libs/simple-mind-map/src/utils/literalText.js'
import {
  buildMindmapSearchHighlightSegments,
  buildMindmapTagFilterOptions,
  collectMindmapCaseReviewNodes,
  isMindmapCaseTitleData,
  matchesMindmapFilterText,
  resolveMindmapCaseReviewIndex,
  resolveMindmapSearchNavigationIndex,
  resolveMindmapSearchResultListHeight,
} from '../mindmap-search.js'

test('脑图替换把正则元字符和替换模板当作普通文本', () => {
  assert.equal(replaceAllLiteralText('a.b.c', '.', '[$&]'), 'a[$&]b[$&]c')
  assert.equal(replaceAllLiteralText('a[b][b]', '[b]', '$1'), 'a$1$1')
  assert.equal(replaceAllLiteralText('路径 \\* 与 \\*', '\\*', '完成'), '路径 完成 与 完成')
})

test('空查找文本不会向每个字符之间插入替换内容', () => {
  assert.equal(replaceAllLiteralText('脑图', '', 'x'), '脑图')
  assert.equal(replaceAllLiteralText(null, 'x', 'y'), '')
})

test('搜索高亮返回纯文本分段并把正则字符当作普通关键词', () => {
  const source = '<img src=x onerror=alert(1)> 计划.plan.PLAN'
  const segments = buildMindmapSearchHighlightSegments(source, '.plan')

  assert.equal(segments.map(item => item.text).join(''), source)
  assert.deepEqual(
    segments.filter(item => item.match).map(item => item.text),
    ['.plan', '.PLAN'],
  )
  assert.equal(segments.some(item => Object.hasOwn(item, 'html')), false)
  assert.deepEqual(buildMindmapSearchHighlightSegments(null, 'x'), [])
})

test('本地搜索高亮可保持与核心插件一致的大小写语义', () => {
  const segments = buildMindmapSearchHighlightSegments('Node node', 'Node', {
    caseSensitive: true,
  })

  assert.deepEqual(segments, [
    { text: 'Node', match: true },
    { text: ' node', match: false },
  ])
})

test('筛选文本运算符保持字面量且区分正向和否定条件', () => {
  assert.equal(matchesMindmapFilterText('登录.P1', 'contains', '.P1'), true)
  assert.equal(matchesMindmapFilterText('登录.P1', 'equals', '登录.P1'), true)
  assert.equal(matchesMindmapFilterText('登录.P1', 'notContains', 'P2'), true)
  assert.equal(matchesMindmapFilterText('登录.P1', 'notEquals', '登录'), true)
  assert.equal(matchesMindmapFilterText('登录.P1', 'contains', 'p1'), false)
})

test('用例标题字段只识别明确标记的节点数据', () => {
  assert.equal(isMindmapCaseTitleData({ tag: ['用例标题'] }), true)
  assert.equal(isMindmapCaseTitleData({ tag: [{ text: '用例标题' }] }), true)
  assert.equal(isMindmapCaseTitleData({ tag: [{ name: '用例标题' }] }), true)
  assert.equal(isMindmapCaseTitleData({ tag: [{ text: 'P1' }] }), false)
  assert.equal(isMindmapCaseTitleData({}), false)
})

test('用例评审按标题和用例子树条件筛选并保持文档顺序', () => {
  const caseA = {
    data: { text: '登录成功', tag: ['用例标题'] },
    children: [{ data: { text: '优先级 P0' }, children: [] }],
  }
  const caseB = {
    data: { text: '登录失败', tag: [{ text: '用例标题' }] },
    children: [{ data: { text: '优先级 P1' }, children: [] }],
  }
  const root = { data: { text: '登录评审' }, children: [caseA, caseB] }
  const options = {
    getData: node => node.data,
    getText: node => node.data.text,
  }

  assert.deepEqual(collectMindmapCaseReviewNodes(root, [
    { field: 'title', operator: 'contains', value: '登录' },
  ], options), [caseA, caseB])
  assert.deepEqual(collectMindmapCaseReviewNodes(root, [
    { field: 'title', operator: 'contains', value: '登录' },
    { field: 'any', operator: 'contains', value: 'P1' },
  ], options), [caseB])
  assert.deepEqual(collectMindmapCaseReviewNodes(root, [
    { field: 'any', operator: 'contains', value: 'P0' },
  ], options), [caseA])
})

test('纯文本和富文本替换共用字面量实现', async () => {
  const plugin = await readFile(
    new URL('../../libs/simple-mind-map/src/plugins/Search.js', import.meta.url),
    'utf8',
  )
  const utils = await readFile(
    new URL('../../libs/simple-mind-map/src/utils/index.js', import.meta.url),
    'utf8',
  )

  assert.match(plugin, /replaceAllLiteralText\(text, searchText, replaceText\)/)
  assert.match(plugin, /text = String\(text \?\? ''\)/)
  assert.match(plugin, /if \(this\.rejectReadonlyReplace\('SEARCH_REPLACE'\)\) return/)
  assert.match(plugin, /if \(this\.rejectReadonlyReplace\('SEARCH_REPLACE_ALL'\)\) return/)
  assert.match(plugin, /this\.mindMap\.emit\('readonly_command_rejected', action\)/)
  assert.match(utils, /replaceDomTextNodes\(replaceHtmlTextEl/)
  assert.match(utils, /replaceAllLiteralText\(value, searchText, replaceText\)/)
  assert.doesNotMatch(plugin, /new RegExp\(searchText/)
  assert.doesNotMatch(utils, /new RegExp\(searchText/)
})

test('重名标签使用范围和稳定 Key 区分且重复 ID 只出现一次', () => {
  const options = buildMindmapTagFilterOptions([
    { id: 1, name: 'P0', tagKey: 'priority_global', ownerId: 0 },
    { id: 2, name: 'P0', tagKey: 'priority_mine', ownerId: 9 },
    { id: 2, name: '旧副本', tagKey: 'duplicate', ownerId: 9 },
    { id: 3, name: '待确认', tagKey: 'todo', ownerId: 0 },
  ])

  assert.deepEqual(options.map(item => item.optionLabel), [
    'P0 · 全局 · priority_global',
    'P0 · 我的 · priority_mine',
    '待确认',
  ])
})

test('搜索结果方向导航支持边界循环与 Home End', () => {
  assert.equal(resolveMindmapSearchNavigationIndex(-1, 4, 'ArrowDown'), 0)
  assert.equal(resolveMindmapSearchNavigationIndex(-1, 4, 'ArrowUp'), 3)
  assert.equal(resolveMindmapSearchNavigationIndex(3, 4, 'ArrowDown'), 0)
  assert.equal(resolveMindmapSearchNavigationIndex(0, 4, 'ArrowUp'), 3)
  assert.equal(resolveMindmapSearchNavigationIndex(2, 4, 'Home'), 0)
  assert.equal(resolveMindmapSearchNavigationIndex(1, 4, 'End'), 3)
})

test('搜索结果方向导航对空列表和非法当前项安全降级', () => {
  assert.equal(resolveMindmapSearchNavigationIndex(0, 0, 'ArrowDown'), -1)
  assert.equal(resolveMindmapSearchNavigationIndex(99, 3, 'ArrowDown'), 0)
  assert.equal(resolveMindmapSearchNavigationIndex(99, 3, 'ArrowUp'), 2)
  assert.equal(resolveMindmapSearchNavigationIndex(1, 3, 'PageDown'), 1)
})

test('用例评审支持从头开始并在最后一条停止', () => {
  assert.equal(resolveMindmapCaseReviewIndex(-1, 3, 'restart'), 0)
  assert.equal(resolveMindmapCaseReviewIndex(0, 3, 'next'), 1)
  assert.equal(resolveMindmapCaseReviewIndex(1, 3, 'next'), 2)
  assert.equal(resolveMindmapCaseReviewIndex(2, 3, 'next'), 2)
  assert.equal(resolveMindmapCaseReviewIndex(-1, 3, 'next'), 0)
  assert.equal(resolveMindmapCaseReviewIndex(0, 0, 'restart'), -1)
  assert.equal(resolveMindmapCaseReviewIndex(99, 3, 'noop'), -1)
})

test('搜索结果高度使用面板下方真实空间并保持可用边界', () => {
  assert.equal(resolveMindmapSearchResultListHeight(900, 300), 480)
  assert.equal(resolveMindmapSearchResultListHeight(600, 300), 288)
  assert.equal(resolveMindmapSearchResultListHeight(320, 260), 96)
  assert.equal(resolveMindmapSearchResultListHeight(Number.NaN, Number.NaN), 96)
})
