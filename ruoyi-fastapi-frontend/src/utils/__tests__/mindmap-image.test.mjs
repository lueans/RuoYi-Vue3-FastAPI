import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MINDMAP_IMAGE_MAX_BYTES,
  getMindmapImageFileError,
  normalizeMindmapImageUrl,
} from '../mindmap-image.js'
import { getSafeMindMapImageUrl } from '../../libs/simple-mind-map/src/utils/image.js'

test('节点图片仅接受大小合规的图片文件', () => {
  assert.equal(getMindmapImageFileError({ type: 'image/png', size: 1024 }), '')
  assert.equal(getMindmapImageFileError({ type: 'text/html', size: 1024 }), '仅支持图片文件')
  assert.equal(
    getMindmapImageFileError({ type: 'image/jpeg', size: MINDMAP_IMAGE_MAX_BYTES + 1 }),
    '图片大小不能超过 5 MB',
  )
})

test('图片 URL 只允许可显示的安全协议和图片 Data URL', () => {
  assert.equal(normalizeMindmapImageUrl(' https://example.com/a.png '), 'https://example.com/a.png')
  assert.equal(normalizeMindmapImageUrl('/images/a.png'), '/images/a.png')
  assert.equal(normalizeMindmapImageUrl('data:image/png;base64,AA=='), 'data:image/png;base64,AA==')
  assert.throws(() => normalizeMindmapImageUrl('javascript:alert(1)'), /仅支持 HTTP/)
  assert.throws(() => normalizeMindmapImageUrl('file:///tmp/a.png'), /仅支持 HTTP/)
  assert.throws(() => normalizeMindmapImageUrl('blob:https://example.com/abc'), /仅支持 HTTP/)
  assert.throws(() => normalizeMindmapImageUrl('https://user:secret@example.com/a.png'), /账号或密码/)
  assert.throws(() => normalizeMindmapImageUrl('https://example.com/a\n.png'), /非法控制字符/)
  assert.throws(() => normalizeMindmapImageUrl(`https://example.com/${'a'.repeat(4096)}`), /不能超过 4096/)
  assert.throws(() => normalizeMindmapImageUrl('data:text/html;base64,AA=='), /仅支持图片 Data URL/)
})

test('图片 Data URL 同样受文档体积上限保护', () => {
  assert.throws(
    () => normalizeMindmapImageUrl(`data:image/png;base64,${'A'.repeat(7 * 1024 * 1024)}`),
    /不能超过 5 MB/,
  )
})

test('渲染安全入口会静默丢弃历史数据中的危险图片地址', () => {
  assert.equal(getSafeMindMapImageUrl('https://example.com/a.png'), 'https://example.com/a.png')
  assert.equal(getSafeMindMapImageUrl('../images/a.png'), '../images/a.png')
  assert.equal(getSafeMindMapImageUrl('data:image/webp;base64,AA=='), 'data:image/webp;base64,AA==')
  assert.equal(getSafeMindMapImageUrl('javascript:alert(1)'), '')
  assert.equal(getSafeMindMapImageUrl('file:///tmp/a.png'), '')
  assert.equal(getSafeMindMapImageUrl('https://user:secret@example.com/a.png'), '')
})

test('节点图片、渲染器和主题背景统一使用安全读取链路并废弃过期结果', async () => {
  const componentRoot = new URL('../../components/MindMap/', import.meta.url)
  const [nodeImage, nodeImagePreview, backgroundUpload, nodeRenderer] = await Promise.all([
    readFile(new URL('NodeImage.vue', componentRoot), 'utf8'),
    readFile(new URL('NodeImgPreview.vue', componentRoot), 'utf8'),
    readFile(new URL('ImgUpload/index.vue', componentRoot), 'utf8'),
    readFile(
      new URL('../../libs/simple-mind-map/src/core/render/node/nodeCreateContents.js', import.meta.url),
      'utf8',
    ),
  ])

  assert.match(nodeImage, /normalizeMindmapImageUrl\(input\)/)
  assert.match(nodeImage, /loadMindmapImageDimensions\(url\)/)
  assert.match(nodeImage, /operationToken !== imageOperationToken/)
  assert.match(nodeImage, /function cancel\(\)[\s\S]*imageOperationToken\+\+/)
  assert.match(nodeImagePreview, /getSafeMindMapImageUrl\(node\?\.getImageUrl\?\.\(\)\)/)
  assert.match(nodeImagePreview, /watch\(\(\) => props\.mindMap,[\s\S]*closeViewer\(\)/)
  assert.match(backgroundUpload, /readMindmapImageFile\(file\)/)
  assert.match(backgroundUpload, /aria-label="选择背景图片"/)
  assert.match(backgroundUpload, /<button class="delBtn"/)
  assert.match(nodeRenderer, /return getSafeMindMapImageUrl\(imageUrl\)/)
  assert.doesNotMatch(nodeRenderer, /new SVGImage\(\)\.load\(this\.getImageUrl\(\)\)/)
})
