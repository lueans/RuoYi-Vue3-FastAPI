import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const keyCommandUrl = new URL(
  '../../libs/simple-mind-map/src/core/command/KeyCommand.js',
  import.meta.url,
)
const textEditUrl = new URL(
  '../../libs/simple-mind-map/src/core/render/TextEdit.js',
  import.meta.url,
)

test('文本编辑结束后恢复快捷键的画布作用域', async () => {
  const source = await readFile(keyCommandUrl, 'utf8')
  const recoveryBody = source.match(/recoveryCheckInSvg\(\) \{([\s\S]*?)\n  \}/)?.[1] || ''

  assert.match(recoveryBody, /this\.isStopCheckInSvg = false/)
  assert.doesNotMatch(recoveryBody, /this\.isStopCheckInSvg = true/)
  assert.match(
    source,
    /enableShortcutOnlyWhenMouseInSvg[\s\S]*!this\.isStopCheckInSvg[\s\S]*!this\.isInSvg/,
  )
})

test('可聚焦画布容器与 body 都能进入统一快捷键处理', async () => {
  const source = await readFile(keyCommandUrl, 'utf8')
  const enableCheckBody = source.match(
    /defaultEnableCheck\(e\) \{([\s\S]*?)\n  \}/,
  )?.[1] || ''

  assert.match(
    enableCheckBody,
    /target === document\.body \|\| target === this\.mindMap\.el/,
  )
  assert.match(enableCheckBody, /if \(!target\?\.classList\) return false/)
})

test('编辑态 Enter 和 Tab 提交文本后基于当前节点继续创建', async () => {
  const source = await readFile(textEditUrl, 'utf8')
  const finishBody = source.match(
    /finishTextEditAndInsert\(command\) \{([\s\S]*?)\n  \}/,
  )?.[1] || ''
  const registerBody = source.match(
    /registerTmpShortcut\(\) \{([\s\S]*?)\n  \}/,
  )?.[1] || ''

  assert.match(finishBody, /const currentNode = this\.getCurrentEditNode\(\)/)
  assert.match(
    finishBody,
    /this\.hideEditTextBox\(\)[\s\S]*this\.mindMap\.execCommand\(command, true, \[currentNode\]\)/,
  )
  assert.match(registerBody, /this\.finishTextEditAndInsert\('INSERT_NODE'\)/)
  assert.match(
    registerBody,
    /this\.finishTextEditAndInsert\('INSERT_CHILD_NODE'\)/,
  )
})

test('节点、富文本、关联线和外框编辑器都成对暂停并恢复作用域检查', async () => {
  const files = [
    '../../libs/simple-mind-map/src/core/render/TextEdit.js',
    '../../libs/simple-mind-map/src/plugins/RichText.js',
    '../../libs/simple-mind-map/src/plugins/associativeLine/associativeLineText.js',
    '../../libs/simple-mind-map/src/plugins/outerFrame/outerFrameText.js',
  ]

  for (const file of files) {
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    assert.match(source, /stopCheckInSvg\(\)/, file)
    assert.match(source, /recoveryCheckInSvg\(\)/, file)
  }
})
