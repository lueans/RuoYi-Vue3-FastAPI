import {
  MIND_MAP_IMAGE_MAX_BYTES,
  MIND_MAP_IMAGE_URL_MAX_LENGTH,
  normalizeMindMapImageUrl,
} from '../libs/simple-mind-map/src/utils/image.js'

export const MINDMAP_IMAGE_MAX_BYTES = MIND_MAP_IMAGE_MAX_BYTES
export const MINDMAP_IMAGE_LOAD_TIMEOUT_MS = 10000
export const MINDMAP_IMAGE_URL_MAX_LENGTH = MIND_MAP_IMAGE_URL_MAX_LENGTH

function formatMegabytes(bytes) {
  return Math.max(1, Math.round(bytes / 1024 / 1024))
}

export function getMindmapImageFileError(file, options = {}) {
  const maxBytes = Number(options.maxBytes) || MINDMAP_IMAGE_MAX_BYTES
  if (!file) return '请选择图片文件'
  if (!String(file.type || '').toLowerCase().startsWith('image/')) {
    return '仅支持图片文件'
  }
  if (Number(file.size) > maxBytes) {
    return `图片大小不能超过 ${formatMegabytes(maxBytes)} MB`
  }
  return ''
}

export function readMindmapImageFile(file, options = {}) {
  const error = getMindmapImageFileError(file, options)
  if (error) return Promise.reject(new Error(error))

  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string' && /^data:image\//i.test(reader.result)) {
        resolve(reader.result)
      } else {
        reject(new Error('图片内容无法识别'))
      }
    }
    reader.onerror = () => reject(new Error('读取图片失败，请重试'))
    reader.onabort = () => reject(new Error('图片读取已取消'))
    reader.readAsDataURL(file)
  })
}

export function normalizeMindmapImageUrl(value, options = {}) {
  return normalizeMindMapImageUrl(value, options)
}

export function loadMindmapImageDimensions(url, options = {}) {
  const timeoutMs = Number(options.timeoutMs) || MINDMAP_IMAGE_LOAD_TIMEOUT_MS
  return new Promise((resolve, reject) => {
    const image = new Image()
    let settled = false
    const finish = (callback) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      image.onload = null
      image.onerror = null
      callback()
    }
    const timer = setTimeout(() => {
      finish(() => reject(new Error('图片加载超时，请检查地址或网络后重试')))
    }, timeoutMs)
    image.onload = () => {
      finish(() => resolve({
        width: image.naturalWidth || image.width || 200,
        height: image.naturalHeight || image.height || 200,
      }))
    }
    image.onerror = () => {
      finish(() => reject(new Error('图片加载失败，请检查文件或地址')))
    }
    image.src = url
  })
}
