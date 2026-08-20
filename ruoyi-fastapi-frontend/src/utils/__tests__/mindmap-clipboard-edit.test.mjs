import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { copyMindmapPngBlob, copyMindmapText } from '../mindmap-clipboard.js'
import { insertMindmapPlainTextAtSelection } from '../mindmap-dom-edit.js'

test('文本复制只有在 Clipboard API 真正完成后才成功', async () => {
  let copied = ''
  assert.equal(await copyMindmapText('脑图内容', {
    clipboard: { writeText: async value => { copied = value } },
  }), true)
  assert.equal(copied, '脑图内容')
  await assert.rejects(copyMindmapText('', { clipboard: null, documentRef: null }), /没有可复制/)
})

test('PNG 复制拒绝无效数据和不支持图片剪贴板的浏览器', async () => {
  const blob = new Blob(['png'], { type: 'image/png' })
  await assert.rejects(copyMindmapPngBlob(blob, { clipboard: null, ClipboardItemCtor: null }), /不支持复制图片/)
  await assert.rejects(copyMindmapPngBlob(new Blob(['text'], { type: 'text/plain' })), /没有可复制的 PNG/)
})

test('大纲粘贴使用 Selection Range 插入纯文本并恢复光标', () => {
  const inserted = []
  const target = { contains: node => node === target }
  const range = {
    commonAncestorContainer: target,
    deleteContents: () => inserted.push('delete'),
    insertNode: node => inserted.push(node.value),
    setStartAfter: node => inserted.push(`after:${node.value}`),
    collapse: value => inserted.push(`collapse:${value}`),
  }
  const selection = {
    rangeCount: 1,
    getRangeAt: () => range,
    removeAllRanges: () => inserted.push('removeRanges'),
    addRange: () => inserted.push('addRange'),
  }
  const documentRef = {
    getSelection: () => selection,
    createTextNode: value => ({ value }),
  }

  assert.equal(insertMindmapPlainTextAtSelection('<b>纯文本</b>', target, { documentRef }), true)
  assert.deepEqual(inserted, [
    'delete', '<b>纯文本</b>', 'after:<b>纯文本</b>', 'collapse:true', 'removeRanges', 'addRange',
  ])
})

test('大纲拒绝把文本插入目标编辑项之外的选区', () => {
  const outside = {}
  const target = { contains: () => false }
  const documentRef = {
    getSelection: () => ({ rangeCount: 1, getRangeAt: () => ({ commonAncestorContainer: outside }) }),
    createTextNode: value => ({ value }),
  }
  assert.equal(insertMindmapPlainTextAtSelection('text', target, { documentRef }), false)
})

test('右键复制和大纲粘贴不再直接调用废弃命令并覆盖全部失败路径', async () => {
  const componentRoot = new URL('../../components/MindMap/', import.meta.url)
  const [contextmenu, outline] = await Promise.all([
    readFile(new URL('Contextmenu.vue', componentRoot), 'utf8'),
    readFile(new URL('OutlineEdit.vue', componentRoot), 'utf8'),
  ])

  assert.match(contextmenu, /copyMindmapPngBlob/)
  assert.match(contextmenu, /copyMindmapText/)
  assert.match(contextmenu, /if \(!png\) throw new Error/)
  assert.match(contextmenu, /if \(!copied\) throw new Error/)
  assert.match(contextmenu, /ElMessage\.error\(error\?\.message \|\| '复制失败'\)/)
  assert.doesNotMatch(contextmenu, /document\.execCommand/)
  assert.match(outline, /insertMindmapPlainTextAtSelection/)
  assert.doesNotMatch(outline, /document\.execCommand/)
})
