import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const componentRoot = new URL('../../components/MindMap/', import.meta.url)
const componentFiles = [
  'NodeImage.vue',
  'NodeHyperlink.vue',
  'NodeAttachment.vue',
  'NodeTag.vue',
]

test('节点批量编辑弹窗统一捕获打开时选区并只写入快照目标', async () => {
  const sources = await Promise.all(
    componentFiles.map(file => readFile(new URL(file, componentRoot), 'utf8')),
  )

  for (const [index, source] of sources.entries()) {
    assert.match(source, /import \{ captureMindmapEditTargets \}/, componentFiles[index])
    assert.match(source, /const editTargets = shallowRef\(\[\]\)/, componentFiles[index])
    assert.match(source, /editTargets\.value = captureMindmapEditTargets\(/, componentFiles[index])
    assert.match(source, /editTargets\.value\.forEach\(/, componentFiles[index])
    assert.doesNotMatch(source, /activeNodes\.value\.forEach\(/, componentFiles[index])
    assert.match(source, /v-if="targetCount > 1"/, componentFiles[index])
    assert.match(source, /打开弹窗时选中的/, componentFiles[index])
    assert.match(source, /:title="dialogTitle"/, componentFiles[index])
    assert.match(source, /width="min\(/, componentFiles[index])
  }
})

test('混合批量状态提供移除入口且标签明确提示差异覆盖', async () => {
  const [image, hyperlink, attachment, tag] = await Promise.all(
    componentFiles.map(file => readFile(new URL(file, componentRoot), 'utf8')),
  )

  assert.match(image, /hasImage = computed\(\(\) => editTargets\.value\.some/)
  assert.match(hyperlink, /hasExistingLink = computed\(\(\) => editTargets\.value\.some/)
  assert.match(attachment, /hasAttachment = computed\(\(\) => editTargets\.value\.some/)
  assert.match(attachment, /captureMindmapEditTargets\(activeNodes\.value, targetNode\)/)
  assert.match(tag, /各节点原有差异标签会被替换/)
  assert.match(tag, /type="warning"/)
})

test('图片和超链接输入弹窗成对暂停画布快捷键并聚焦首个输入框', async () => {
  const sources = await Promise.all([
    readFile(new URL('NodeImage.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeHyperlink.vue', componentRoot), 'utf8'),
  ])

  for (const source of sources) {
    assert.match(source, /@open="on(?:Dialog)?Open"/)
    assert.match(source, /bus\.emit\('startTextEdit'\)/)
    assert.match(source, /bus\.emit\('endTextEdit'\)/)
    assert.match(source, /nextTick\(\(\) => [a-zA-Z]+InputRef\.value\?\.focus\(\)\)/)
  }
})

test('节点属性弹窗在只读切换后关闭并在执行边界拒绝写入', async () => {
  const sources = await Promise.all(
    componentFiles.map(file => readFile(new URL(file, componentRoot), 'utf8')),
  )
  const toolbar = await readFile(new URL('Toolbar.vue', componentRoot), 'utf8')

  for (const [index, source] of sources.entries()) {
    assert.match(source, /const isReadonly = computed\(\(\) => props\.readonly \|\| store\.isReadonly\)/, componentFiles[index])
    assert.match(source, /watch\(isReadonly,[\s\S]*dialogVisible\.value = false/, componentFiles[index])
    assert.match(source, /if \(isReadonly\.value[^\n]*\) return/, componentFiles[index])
  }

  assert.match(toolbar, /<NodeImage :readonly="isReadonly"/)
  assert.match(toolbar, /<NodeHyperlink :readonly="isReadonly"/)
  assert.match(toolbar, /<NodeTag :readonly="isReadonly"/)
  assert.match(sources[0], /operationToken !== imageOperationToken \|\| isReadonly\.value/)
  assert.match(sources[1], /function confirm\(\) \{\s*if \(isReadonly\.value \|\| editTargets\.value\.length === 0\) return/)
  assert.match(sources[2], /function removeAttachment\(\) \{\s*if \(isReadonly\.value \|\| editTargets\.value\.length === 0\) return/)
  assert.match(sources[3], /function isCurrentDialogSession\(sessionId\)/)
  assert.match(sources[3], /!isReadonly\.value/)
})
