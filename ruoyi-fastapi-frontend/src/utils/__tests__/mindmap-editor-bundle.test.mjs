import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('编辑器首屏不静态加载 PDF 和 XMind 重型导出插件', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/usePlugins.js', import.meta.url),
    'utf8',
  )

  assert.equal(
    /import\s+Export(?:PDF|XMind)\s+from/.test(source),
    false,
  )
  assert.match(source, /pdf:\s*\(\)\s*=>\s*import\(['"]@mind-map\/src\/plugins\/ExportPDF\.js['"]\)/)
  assert.match(source, /xmind:\s*\(\)\s*=>\s*import\(['"]@mind-map\/src\/plugins\/ExportXMind\.js['"]\)/)
})

test('重型公式引擎按需加载且文档能力使用统一加载边界', async () => {
  const [pluginSource, loaderSource, editorSource, formulaSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/usePlugins.js', import.meta.url), 'utf8'),
    readFile(new URL('../mindmap-plugin-loader.js', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/FormulaSidebar.vue', import.meta.url), 'utf8'),
  ])

  assert.doesNotMatch(pluginSource, /import\s+Formula\s+from/)
  for (const plugin of ['Formula', 'AssociativeLine', 'OuterFrame', 'MindMapLayoutPro']) {
    assert.match(loaderSource, new RegExp(`import\\(['"]@mind-map/src/plugins/${plugin}(?:\\.js)?['"]\\)`))
  }
  // 这三项需要同步处理 Yjs 增量，因此编辑器常驻；只读预览仍通过统一加载器按需加载。
  for (const plugin of ['AssociativeLine', 'OuterFrame', 'MindMapLayoutPro']) {
    assert.match(pluginSource, new RegExp(`import\\s+${plugin}\\s+from`))
  }
  const ensureIndex = editorSource.indexOf('await ensureMindmapDocumentPlugins({ root, layout })')
  const createIndex = editorSource.indexOf('new MindMap({', ensureIndex)
  assert.ok(ensureIndex > 0 && createIndex > ensureIndex)
  assert.match(loaderSource, /featurePluginPromises\.delete\(feature\)/)
  assert.match(formulaSource, /const activeMindMap = props\.mindMap[\s\S]*await ensureFormulaPlugin\(activeMindMap\)/)
  assert.match(formulaSource, /role="status" aria-live="polite"/)
  assert.match(formulaSource, /role="alert"/)
  assert.match(formulaSource, /@click="loadFormulaPlugin">重新加载/)
  assert.match(formulaSource, /isCurrentPluginRequest\(requestId, activeMindMap\)/)
})

test('运行期替换文档会先补齐插件且拒绝迟到会话', async () => {
  const [editorSource, versionSource, importSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/VersionHistory.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Import.vue', import.meta.url), 'utf8'),
  ])

  assert.ok((editorSource.match(/await ensureMindmapDocumentPlugins\(/g) || []).length >= 5)
  assert.match(editorSource, /mindMap\.value !== activeMindMap/)
  const versionEnsureIndex = versionSource.indexOf('await ensureMindmapDocumentPlugins(data, mindMap)')
  const versionApplyIndex = versionSource.indexOf('mindMap.setFullData(data)', versionEnsureIndex)
  assert.ok(versionEnsureIndex > 0 && versionApplyIndex > versionEnsureIndex)
  assert.match(importSource, /await new Promise\(\(resolve, reject\) => \{[\s\S]*bus\.emit\('setData', data, \{ resolve, reject \}\)/)
  assert.match(editorSource, /request\.resolve\?\.\(true\)/)
  assert.match(editorSource, /request\.reject\?\.\(error\)/)
  assert.match(editorSource, /服务端已经提交本批操作，渲染插件失败不能把同一批操作当成网络失败重试/)
  assert.match(editorSource, /blockedConflictData = \{ currentRevision: contentRevision \}/)
  assert.match(editorSource, /云端已保存，但画布刷新失败/)
  assert.match(editorSource, /prepareDocument: \(document, targetMindMap\) => \{/)
  assert.match(editorSource, /features\.includes\(MINDMAP_PREVIEW_FEATURES\.formula\)[\s\S]*!targetMindMap\?\.formula/)
  assert.match(editorSource, /onDocumentPrepareExhausted:/)
})

test('Markdown 和纯文本转换器仅在选择对应格式时加载', async () => {
  const source = await readFile(
    new URL('../../libs/simple-mind-map/src/plugins/Export.js', import.meta.url),
    'utf8',
  )

  assert.equal(/import\s+\{\s*transformTo(?:Markdown|Txt)/.test(source), false)
  assert.match(source, /await import\(['"]\.\.\/parse\/toMarkdown['"]\)/)
  assert.match(source, /await import\(['"]\.\.\/parse\/toTxt['"]\)/)
})

test('编辑器执行统一导出请求前会确保目标格式插件已就绪', async () => {
  const source = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /bus\.on\('exportRequest', onExportRequest\)/)
  assert.match(source, /const activeMindMap = mindMap\.value/)
  assert.match(source, /await ensureExportPlugins\(activeMindMap, type\)/)
  assert.match(source, /await activeMindMap\.export\(type, true, name, \.\.\.args\)/)
  assert.match(source, /activeMindMap !== mindMap\.value/)
  assert.match(source, /request\.reject\?\.\(error\)/)
})
