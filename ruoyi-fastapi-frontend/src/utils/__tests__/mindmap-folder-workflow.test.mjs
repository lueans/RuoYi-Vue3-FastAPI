import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  formatFolderDeletePrompt,
  getFolderSubtreeIds,
  normalizeFolderTarget,
  pruneFolderTree,
  validateFolderName,
} from '../mindmap-folder.js'

const indexSourceUrl = new URL('../../views/mindmap/index.vue', import.meta.url)
const apiSourceUrl = new URL('../../api/mindmap/folder.js', import.meta.url)
const migrationSourceUrl = new URL(
  '../../../../ruoyi-fastapi-backend/migrations/20260818_mindmap_folder_lifecycle.sql',
  import.meta.url,
)

const tree = [
  {
    id: 1,
    name: '产品',
    children: [
      { id: 2, name: '需求', children: [{ id: 3, name: '历史需求' }] },
    ],
  },
  { id: 4, name: '研发' },
]

test('目录名称校验与后端保持一致', () => {
  assert.deepEqual(validateFolderName('  产品规划  '), {
    valid: true,
    value: '产品规划',
    message: '',
  })
  assert.equal(validateFolderName(' ').valid, false)
  assert.equal(validateFolderName('产品/规划').valid, false)
  assert.equal(validateFolderName('产品\\规划').valid, false)
  assert.equal(validateFolderName('标题\n注入').valid, false)
  assert.equal(validateFolderName('标题\u0085注入').valid, false)
  assert.equal(validateFolderName(123).valid, false)
  assert.equal(validateFolderName('脑'.repeat(101)).valid, false)
})

test('编辑目录时排除自身及全部后代但不修改原树', () => {
  const subtreeIds = getFolderSubtreeIds(tree, 2)
  const pruned = pruneFolderTree(tree, 2)

  assert.deepEqual([...subtreeIds], [2, 3])
  assert.deepEqual(pruned, [
    { id: 1, name: '产品', children: [] },
    { id: 4, name: '研发' },
  ])
  assert.equal(tree[0].children[0].id, 2)
})

test('删除确认文案展示真实影响且明确脑图不会删除', () => {
  assert.equal(
    formatFolderDeletePrompt({ folderName: '产品', subfolderCount: 2, mindmapCount: 5 }),
    '删除“产品”后，并同时删除 2 个子文件夹，其中 5 张脑图会移至根目录，脑图内容不会删除。',
  )
  assert.match(
    formatFolderDeletePrompt({ folderName: '空目录', subfolderCount: 0, mindmapCount: 0 }),
    /没有脑图会被删除/,
  )
})

test('根目录目标统一转换为后端 null 契约', () => {
  assert.equal(normalizeFolderTarget(0), null)
  assert.equal(normalizeFolderTarget(null), null)
  assert.equal(normalizeFolderTarget('8'), 8)
})

test('目录页面具备加载恢复、影响确认、写操作锁和竞态保护', async () => {
  const [source, apiSource] = await Promise.all([
    readFile(indexSourceUrl, 'utf8'),
    readFile(apiSourceUrl, 'utf8'),
  ])

  assert.match(source, /folderTreeLoading/)
  assert.match(source, /folderTreeError/)
  assert.match(source, /folderRequests = createLatestRequestTracker\(\)/)
  assert.match(source, /getFolderDeleteImpact/)
  assert.match(source, /formatFolderDeletePrompt/)
  assert.match(source, /getFolderSubtreeIds/)
  assert.match(source, /operationType\.value = 'folder:sort'/)
  assert.match(source, /folderFormSelectTree/)
  assert.match(source, /normalizeFolderTarget\(moveFolderId\.value\)/)
  assert.match(source, /:aria-label="`管理文件夹 \$\{data\.name\}`"/)
  assert.match(source, /const canRemoveFolders = computed/)
  assert.match(source, /command === 'delete' && !canRemoveFolders\.value/)
  assert.match(source, /&:focus-within \.node-more/)
  assert.doesNotMatch(source, /\$refs\['folderFormRef'\]/)
  assert.match(apiSource, /\/mindmap\/folder\/' \+ folderId \+ '\/impact'/)
})

test('数据库迁移提供活动同级唯一约束和目录查询索引', async () => {
  const source = await readFile(migrationSourceUrl, 'utf8')
  assert.match(source, /uq_mindmap_folder_active_sibling/)
  assert.match(source, /GENERATED ALWAYS AS/)
  assert.match(source, /idx_mindmap_owner_folder/)
})
