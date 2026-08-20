// 全屏事件检测
const getOnfullscreEnevt = () => {
  if ('onfullscreenchange' in document) {
    return 'onfullscreenchange'
  } else if ('onwebkitfullscreenchange' in document) {
    return 'onwebkitfullscreenchange'
  } else if ('onmozfullscreenchange' in document) {
    return 'onmozfullscreenchange'
  } else if ('onMSFullscreenChange' in document) {
    return 'onmsfullscreenchange'
  }
}

export const fullscrrenEvent = getOnfullscreEnevt()

export const getFullscreenElement = () => (
  document.fullscreenElement ||
  document.webkitFullscreenElement ||
  document.mozFullScreenElement ||
  document.msFullscreenElement ||
  null
)

export const isFullscreenSupported = element => Boolean(
  element?.requestFullscreen ||
  element?.webkitRequestFullscreen ||
  element?.webkitRequestFullScreen ||
  element?.mozRequestFullScreen ||
  element?.msRequestFullscreen
)

// 全屏。统一返回 Promise，调用方可以处理浏览器拒绝或能力缺失。
export const fullScreen = element => {
  const request = element?.requestFullscreen ||
    element?.webkitRequestFullscreen ||
    element?.webkitRequestFullScreen ||
    element?.mozRequestFullScreen ||
    element?.msRequestFullscreen
  if (!request) {
    return Promise.reject(new Error('当前浏览器不支持全屏模式'))
  }
  try {
    return Promise.resolve(request.call(element))
  } catch (error) {
    return Promise.reject(error)
  }
}

export const exitFullScreen = () => {
  if (!getFullscreenElement()) return Promise.resolve()
  const exit = document.exitFullscreen ||
    document.webkitExitFullscreen ||
    document.webkitCancelFullScreen ||
    document.mozCancelFullScreen ||
    document.msExitFullscreen
  if (!exit) return Promise.reject(new Error('当前浏览器无法退出全屏模式'))
  try {
    return Promise.resolve(exit.call(document))
  } catch (error) {
    return Promise.reject(error)
  }
}

export const waitForFullscreenElement = (expectedElement, timeoutMs = 750) => new Promise(resolve => {
  const startedAt = Date.now()
  const check = () => {
    if (getFullscreenElement() === expectedElement) {
      resolve(true)
      return
    }
    if (Date.now() - startedAt >= timeoutMs) {
      resolve(false)
      return
    }
    setTimeout(check, 25)
  }
  check()
})

export const requestFullscreenAndWait = async (element, timeoutMs = 750) => {
  let requestError = null
  void fullScreen(element).catch(error => {
    requestError = error
  })
  const entered = await waitForFullscreenElement(element, timeoutMs)
  if (requestError) throw requestError
  return entered
}

export const exitFullscreenAndWait = async (timeoutMs = 750) => {
  let requestError = null
  void exitFullScreen().catch(error => {
    requestError = error
  })
  const exited = await waitForFullscreenElement(null, timeoutMs)
  if (requestError) throw requestError
  return exited
}

// 文件转buffer
export const fileToBuffer = file => {
  return new Promise(r => {
    const reader = new FileReader()
    reader.onload = () => {
      r(reader.result)
    }
    reader.readAsArrayBuffer(file)
  })
}

// 复制文本到剪贴板
export const setDataToClipboard = data => {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(data)
  }
}

// 复制图片到剪贴板
export const setImgToClipboard = img => {
  if (navigator.clipboard && navigator.clipboard.write) {
    const data = [new ClipboardItem({ ['image/png']: img })]
    navigator.clipboard.write(data)
  }
}

// 打印大纲
export const printOutline = el => {
  const printContent = el.outerHTML
  const iframe = document.createElement('iframe')
  iframe.setAttribute('style', 'position: absolute; width: 0; height: 0;')
  document.body.appendChild(iframe)
  const iframeDoc = iframe.contentWindow.document
  // 将当前页面的所有样式添加到iframe中
  const styleList = document.querySelectorAll('style')
  Array.from(styleList).forEach(el => {
    iframeDoc.write(el.outerHTML)
  })
  // 设置打印展示方式 - 纵向展示
  iframeDoc.write('<style media="print">@page {size: portrait;}</style>')
  // 写入内容
  iframeDoc.write('<div>' + printContent + '</div>')
  setTimeout(function() {
    iframe.contentWindow?.print()
    document.body.removeChild(iframe)
  }, 500)
}

export const getParentWithClass = (el, className) => {
  if (el.classList.contains(className)) {
    return el
  }
  if (el.parentNode && el.parentNode !== document.body) {
    return getParentWithClass(el.parentNode, className)
  }
  return null
}
