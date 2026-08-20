import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const sourceUrl = new URL('../../components/MindMap/NodeTagStyle.vue', import.meta.url)

test('节点标签编辑器具备对话框语义、键盘关闭和焦点生命周期', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /role="dialog"/)
  assert.match(source, /aria-label="编辑节点标签"/)
  assert.match(source, /@keydown\.esc\.stop\.prevent="hide"/)
  assert.match(source, /aria-label="标签名称"/)
  assert.match(source, /aria-label="标签位置"/)
  assert.match(source, /aria-label="标签对齐"/)
  assert.match(source, /aria-label="标签字号"/)
  assert.match(source, /tagTextInputRef\.value\?\.input/)
  assert.match(source, /!containerRef\.value\?\.contains\(activeElement\)/)
  assert.match(source, /returnTarget\?\.isConnected && returnTarget\.focus\?\.\(\)/)
})

test('统一标签定义按最新值串行保存并隔离过期权限请求', async () => {
  const source = await readFile(sourceUrl, 'utf8')

  assert.match(source, /createLatestSerialTaskQueue\(\{[\s\S]*?delayMs: 250,[\s\S]*?execute: persistManagedDefinition/)
  assert.match(source, /const sequence = \+\+managedUpdateSequence[\s\S]*?if \(currentManagedTag\?\.tagId\)/)
  assert.match(source, /sequence === managedUpdateSequence[\s\S]*hasCurrentTagTarget\(\)[\s\S]*currentNode === node[\s\S]*!isReadonly\.value[\s\S]*response\?\.data/)
  assert.match(source, /catch \{[\s\S]*?sequence === managedUpdateSequence && hasCurrentTagTarget\(\) && currentNode === node/)
  assert.equal((source.match(/!isCurrent\(\)/g) || []).length >= 4, true)
  assert.match(source, /function hasCurrentTagTarget\(\)[\s\S]*currentMindMap === props\.mindMap/)
  assert.match(source, /function getEditableTagList\(\)[\s\S]*style: \{ \.\.\.\(tag\.style \|\| \{\}\) \}/)
  assert.match(source, /if \(mm !== oldMm\) hideWithoutFocusRestore\(\)/)
  assert.match(source, /managedDefinitionSaveQueue\.schedule\(pendingModel\)/)
  assert.match(source, /validateMindmapTagDisplayName\(normalizedPatch\.name\)/)
  assert.match(source, /validateMindmapTagStyle\(\{[\s\S]*\.\.\.normalizedPatch\.style/)
  assert.equal((source.match(/validateMindmapTagColor\(color/g) || []).length, 2)
  assert.equal((source.match(/managedDefinitionSaveQueue\.cancel\(\)/g) || []).length >= 2, true)
  assert.doesNotMatch(source, /managedUpdateTimer/)
})
