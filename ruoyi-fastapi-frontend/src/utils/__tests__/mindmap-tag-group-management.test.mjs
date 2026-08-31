import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = await readFile(
  new URL('../../views/mindmap/tags.vue', import.meta.url),
  'utf8',
)

test('标签分组在侧栏直接提供新增、编辑、删除和拖拽排序', () => {
  assert.match(source, /aria-label="新建标签分组"[\s\S]*@click="openCreateCategory"/)
  assert.equal((source.match(/class="tagGroupSortableList"/g) || []).length, 2)
  assert.equal((source.match(/handle="\.tagGroupDragHandle"/g) || []).length, 2)
  assert.match(source, /@click\.stop="openEditCategory\(category\)"/)
  assert.match(source, /@click\.stop="removeCategory\(category\)"/)
  assert.doesNotMatch(source, /openCategoryManager/)
})

test('全局与个人分组独立排序并在失败时恢复服务端顺序', () => {
  assert.match(source, /function canReorderCategoryScope\(scope\)/)
  assert.match(source, /scope === 'global' \? isAdmin\.value : true/)
  assert.match(source, /@start="captureCategoryOrder\('global'\)"/)
  assert.match(source, /@start="captureCategoryOrder\('mine'\)"/)
  assert.match(source, /await reorderTagCategories\(categoryIds\)/)
  assert.match(source, /catch \(error\) \{[\s\S]*await loadCategories\(\)/)
})

test('有标签的分组不能从侧栏删除', () => {
  assert.match(source, /请先移动或删除分组内的标签/)
  assert.match(source, /:disabled="Number\(category\.tagCount\) > 0 \|\| Boolean\(categoryReordering\)"/)
  assert.match(source, /if \(!canRemoveCategoryRow\(row\) \|\| Number\(row\?\.tagCount\) > 0 \|\| categoryReordering\.value\) return/)
})
