import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  canUseMindmapFolders,
  hasAnyPermission,
  MINDMAP_FILE_PERMISSIONS
} from '../mindmap-permission.js'

test('脑图文件权限同时兼容新旧命名空间', () => {
  assert.equal(hasAnyPermission(['mindmap:add'], MINDMAP_FILE_PERMISSIONS.add), true)
  assert.equal(hasAnyPermission(['mindmap:mindmap:add'], MINDMAP_FILE_PERMISSIONS.add), true)
  assert.equal(hasAnyPermission(['mindmap:query'], MINDMAP_FILE_PERMISSIONS.add), false)
})

test('超级管理员和文件夹查看权限可以加载目录树', () => {
  assert.equal(canUseMindmapFolders(['*:*:*']), true)
  assert.equal(canUseMindmapFolders(['mindmap:folder:list']), true)
  assert.equal(canUseMindmapFolders(['mindmap:list']), false)
  assert.equal(canUseMindmapFolders(undefined), false)
})

test('simple-mind-map 只读命令总线只允许浏览行为', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/command/Command.js', import.meta.url),
    'utf8',
  )

  for (const command of [
    'SET_NODE_ACTIVE', 'CLEAR_ACTIVE_NODE', 'GO_TARGET_NODE',
    'SELECT_ALL', 'SET_NODE_EXPAND', 'EXPAND_ALL', 'UNEXPAND_ALL', 'UNEXPAND_TO_LEVEL',
  ]) {
    assert.equal(source.includes(`'${command}'`), true)
  }
  for (const command of ['SET_NODE_TEXT', 'INSERT_NODE', 'REMOVE_NODE', 'RESET_LAYOUT']) {
    assert.equal(source.match(/const READONLY_COMMANDS = new Set\(\[([\s\S]*?)\]\)/)?.[1].includes(`'${command}'`), false)
  }
  assert.match(source, /if \(this\.mindMap\.opt\.readonly && !READONLY_COMMANDS\.has\(name\)\) \{[\s\S]*?return/)
})

test('只读模式的节点选中只更新导航标记，不开放通用节点写入', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/core/render/Render.js', import.meta.url),
    'utf8',
  )
  assert.match(source, /setNodeActive\(node, active\) \{[\s\S]*if \(this\.mindMap\.opt\.readonly\) \{[\s\S]*node\.nodeData\.data\.isActive = active/)
  assert.match(source, /else \{[\s\S]*this\.mindMap\.execCommand\('SET_NODE_DATA', node/)
})
