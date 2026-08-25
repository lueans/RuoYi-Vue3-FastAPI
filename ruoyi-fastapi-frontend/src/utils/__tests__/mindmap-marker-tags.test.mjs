import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  getMindmapManagedMarkerTagIconKey,
  getMindmapMarkerTagIconKey,
  MINDMAP_MARKER_GROUP_SPECS,
  normalizeMindmapMarkerIconKey,
  replaceMindmapMarkerInTagList,
} from '../mindmap-marker-tag-core.js'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)

test('内置脑图标记目录完整且只解析白名单图标', () => {
  assert.equal(MINDMAP_MARKER_GROUP_SPECS.length, 4)
  assert.equal(MINDMAP_MARKER_GROUP_SPECS.flatMap(group => group.options).length, 61)
  assert.equal(normalizeMindmapMarkerIconKey('priority_10'), 'priority_10')
  assert.equal(normalizeMindmapMarkerIconKey('priority_11'), '')
  assert.equal(normalizeMindmapMarkerIconKey('<svg onload=alert(1)>'), '')
  assert.equal(getMindmapManagedMarkerTagIconKey({
    tagKey: 'builtin_marker_priority_1',
    style: { iconKey: 'priority_1' },
  }), 'priority_1')
  assert.equal(getMindmapManagedMarkerTagIconKey({
    tagKey: 'builtin_marker_priority_2',
    style: { iconKey: 'priority_1' },
  }), '')
})

test('同一标记分组保持单选，普通标签仍可并存', () => {
  const tags = [
    { tagId: 1, text: '普通标签', style: { fill: '#fff' } },
    { tagId: 2, text: '优先级 1', style: { iconKey: 'priority_1' } },
    { tagId: 3, text: '任务 1', style: { iconKey: 'progress_1' } },
  ]
  const next = { tagId: 4, text: '优先级 2', style: { iconKey: 'priority_2' } }
  const result = replaceMindmapMarkerInTagList(tags, next)

  assert.deepEqual(result.map(tag => tag.tagId), [1, 3, 4])
  assert.equal(getMindmapMarkerTagIconKey(result[2]), 'priority_2')
})

test('标记入口和节点渲染已统一迁移到标签体系', async () => {
  const [toolbar, trigger, editor, nodeTag, renderer] = await Promise.all([
    readFile(new URL('Toolbar.vue', componentRoot), 'utf8'),
    readFile(new URL('SidebarTrigger.vue', componentRoot), 'utf8'),
    readFile(new URL('Edit.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeTag.vue', componentRoot), 'utf8'),
    readFile(
      new URL('../../libs/simple-mind-map/src/core/render/node/nodeCreateContents.js', import.meta.url),
      'utf8',
    ),
  ])

  assert.doesNotMatch(toolbar, /nodeIconSidebar|icon: '图标'/u)
  assert.match(toolbar, /tag: \{ icon: 'iconbiaoqian', event: 'openSidebar', args: \['nodeTagSidebar'\] \}/u)
  assert.match(trigger, /if \(item\?\.action\)[\s\S]*bus\.emit\(item\.action\)/u)
  assert.match(editor, /<NodeTagSidebar[\s\S]*activeSidebar === 'nodeTagSidebar'/u)
  assert.doesNotMatch(editor, /<NodeIconSidebar|NodeIconToolbar/u)
  assert.match(nodeTag, /replaceMindmapMarkerInTagList/u)
  assert.match(renderer, /itemStyle\?\.iconKey[\s\S]*getNodeIconListIcon/u)
  assert.doesNotMatch(renderer, /tagData\.slice\(0, maxTag\)/u)
  assert.match(renderer, /if \(!markerSrc && textTagCount >= maxTag\) return/u)
})
