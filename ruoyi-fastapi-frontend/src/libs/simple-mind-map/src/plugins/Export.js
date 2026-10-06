import {
  imgToDataUrl,
  downloadFile,
  readBlob,
  removeHTMLEntities,
  handleSelfCloseTags,
  addXmlns,
  addSafeSvgTitle,
  stringifyJsonValueIterative
} from '../utils'
import { SVG } from '@svgdotjs/svg.js'
import drawBackgroundImageToCanvas from '../utils/simulateCSSBackgroundInCanvas'
import { ERROR_TYPES } from '../constants/constant'
import { abortableExport, captureAfterMindmapRender, createExportSession, loadExportImage, throwIfExportAborted } from '../utils/exportSession'

//  导出插件
class Export {
  //  构造函数
  constructor(opt) {
    this.mindMap = opt.mindMap
    this.exportSessions = new Set()
  }

  //  导出
  async export(type, isDownload = true, name = '思维导图', ...args) {
    if (typeof this[type] !== 'function') return null
    // Optional trailing request options do not change existing format arguments.
    const options = args.at(-1)?.exportOptions ? args.pop().exportOptions : {}
    const session = createExportSession(this.mindMap, options)
    this.exportSessions.add(session)
    // Each invocation owns its signal/config. Late cleanup never targets a new
    // export, including retries after timeout or a dialog cancellation.
    const task = Object.create(this)
    task.exportSession = session
    task.exportConfig = { ...this.mindMap.opt }
    task.exportTheme = { ...this.mindMap.themeConfig }
    try {
      session.check()
      const result = await abortableExport(task[type](name, ...args), session.signal)
      session.check()
      if (isDownload) downloadFile(result, name + '.' + type)
      return result
    } finally {
      session.dispose()
      this.exportSessions.delete(session)
    }
  }

  beforePluginRemove() {
    this.exportSessions.forEach(session => session.abort())
  }

  beforePluginDestroy() {
    this.beforePluginRemove()
  }

  // 创建图片url转换任务
  createTransformImgTaskList(svg, tagName, propName, getUrlFn) {
    const imageList = svg.find(tagName)
    return imageList.map(async item => {
      const imgUlr = getUrlFn(item)
      // 已经是data:URL形式不用转换
      if (/^data:/.test(imgUlr) || imgUlr === 'none') {
        return
      }
      const imgData = await imgToDataUrl(imgUlr, false, { signal: this.exportSession?.signal })
      throwIfExportAborted(this.exportSession?.signal)
      item.attr(propName, imgData)
    })
  }

  //  获取svg数据
  async getSvgData(node) {
    let {
      exportPaddingX,
      exportPaddingY,
      errorHandler,
      resetCss,
      addContentToHeader,
      addContentToFooter,
      handleBeingExportSvg
    } = this.exportConfig || this.mindMap.opt
    const signal = this.exportSession?.signal
    let { svg, svgHTML, clipData } = await captureAfterMindmapRender(this.mindMap, () => {
      // Theme/background and SVG belong to the same completed render, even
      // when a theme change arrived while this export waited for layout.
      this.exportTheme = { ...this.mindMap.themeConfig }
      if (node) {
        node = this.mindMap.renderer.findNodeByUid(node.getData('uid'))
        if (!node) throw new Error('导出节点已变化，请重新选择')
      }
      return this.mindMap.getSvgData({
        paddingX: exportPaddingX,
        paddingY: exportPaddingY,
        addContentToHeader,
        addContentToFooter,
        node
      })
    }, { signal })
    throwIfExportAborted(signal)
    if (clipData) {
      clipData.paddingX = exportPaddingX
      clipData.paddingY = exportPaddingY
    }
    let svgIsChange = false
    // svg的image标签，把图片的url转换成data:url类型，否则导出会丢失图片
    const task1 = this.createTransformImgTaskList(
      svg,
      'image',
      'href',
      item => {
        return item.attr('href') || item.attr('xlink:href')
      }
    )
    // html的img标签
    const task2 = this.createTransformImgTaskList(svg, 'img', 'src', item => {
      return item.attr('src')
    })
    const taskList = [...task1, ...task2]
    try {
      await Promise.all(taskList)
    } catch (error) {
      throwIfExportAborted(signal)
      errorHandler(ERROR_TYPES.EXPORT_LOAD_IMAGE_ERROR, error)
      throw new Error('部分节点图片无法加载，已取消导出。请检查图片地址或改用 JSON 备份。', { cause: error })
    }
    // 开启了节点富文本编辑，需要增加一些样式
    if (this.mindMap.richText) {
      const foreignObjectList = svg.find('foreignObject')
      if (foreignObjectList.length > 0) {
        foreignObjectList[0].add(SVG(`<style>${resetCss}</style>`))
        svgIsChange = true
      }
      // 如果还开启了数学公式，还要插入katex库的样式
      if (this.mindMap.formula) {
        const formulaList = svg.find('.ql-formula')
        if (formulaList.length > 0) {
          const styleText = this.mindMap.formula.getStyleText()
          if (styleText) {
            const styleEl = document.createElement('style')
            styleEl.innerHTML = styleText
            addXmlns(styleEl)
            foreignObjectList[0].add(styleEl)
            svgIsChange = true
          }
        }
      }
    }
    // 自定义处理svg的方法
    if (typeof handleBeingExportSvg === 'function') {
      svgIsChange = true
      svg = handleBeingExportSvg(svg)
    }
    // svg节点内容有变，需要重新获取html字符串
    if (taskList.length > 0 || svgIsChange) {
      svgHTML = svg.svg()
    }
    return {
      node: svg,
      str: svgHTML,
      clipData
    }
  }

  //   svg转png
  async svgToPng(
    svgSrc,
    transparent,
    clipData = null,
    fitBg = false,
    format = 'image/png'
  ) {
    const { maxCanvasSize, maxExportImgPixels, minExportImgCanvasScale } = this.exportConfig || this.mindMap.opt
    const signal = this.exportSession?.signal
    const img = await loadExportImage(svgSrc, signal)
    let canvas
    const release = () => {
      if (canvas) { canvas.width = 0; canvas.height = 0 }
      img.src = ''
    }
    signal?.addEventListener('abort', release, { once: true })
    try {
      throwIfExportAborted(signal)
      canvas = document.createElement('canvas')
      const dpr = Math.max(window.devicePixelRatio, minExportImgCanvasScale)
      // 图片原始大小
      let imgWidth = img.width
      let imgHeight = img.height
      // 如果是裁减操作的话，那么需要手动添加内边距，及调整图片大小为实际的裁减区域的大小，不要忘了内边距哦
      let paddingX = 0
      let paddingY = 0
      if (clipData) {
        paddingX = clipData.paddingX
        paddingY = clipData.paddingY
        imgWidth = clipData.width + paddingX * 2
        imgHeight = clipData.height + paddingY * 2
      }
      // 适配背景图片的大小
      let fitBgImgWidth = 0
      let fitBgImgHeight = 0
      const { backgroundImage } = (this.exportTheme || this.mindMap.themeConfig)
      if (fitBg && backgroundImage && backgroundImage !== 'none' && !transparent) {
        const bgImg = await loadExportImage(backgroundImage, signal)
        const bgImgSize = [bgImg.width, bgImg.height]
        bgImg.src = ''
        throwIfExportAborted(signal)
        if (bgImgSize) {
          const imgRatio = imgWidth / imgHeight
          const bgRatio = bgImgSize[0] / bgImgSize[1]
          if (imgRatio > bgRatio) {
            fitBgImgWidth = imgWidth
            fitBgImgHeight = imgWidth / bgRatio
          } else {
            fitBgImgHeight = imgHeight
            fitBgImgWidth = imgHeight * bgRatio
          }
        }
      }
      // 检查是否超出canvas支持的像素上限
      // canvas大小需要乘以dpr
      let canvasWidth = (fitBgImgWidth || imgWidth) * dpr
      let canvasHeight = (fitBgImgHeight || imgHeight) * dpr
      if (!Number.isFinite(canvasWidth) || !Number.isFinite(canvasHeight)
        || canvasWidth <= 0 || canvasHeight <= 0) {
        throw new Error('脑图图片尺寸无效，请使用 SVG 或 JSON 导出。')
      }
      const dimensionLimit = Number.isFinite(maxCanvasSize) && maxCanvasSize >= 1
        ? Math.floor(maxCanvasSize) : 16384
      const pixelLimit = Number.isFinite(maxExportImgPixels) && maxExportImgPixels >= 1
        ? Math.floor(maxExportImgPixels) : 16 * 1024 * 1024
      const scale = Math.min(
        1,
        dimensionLimit / canvasWidth,
        dimensionLimit / canvasHeight,
        Math.sqrt(pixelLimit / canvasWidth / canvasHeight)
      )
      const sourceWidth = canvasWidth
      const sourceHeight = canvasHeight
      canvasWidth = Math.max(1, Math.floor(canvasWidth * scale))
      canvasHeight = Math.max(1, Math.floor(canvasHeight * scale))
      // 极端长宽比可能把一边向上取整为 1，仍须遵守总像素预算。
      canvasWidth = Math.min(canvasWidth, Math.max(1, Math.floor(pixelLimit / canvasHeight)))
      canvasHeight = Math.min(canvasHeight, Math.max(1, Math.floor(pixelLimit / canvasWidth)))
      const scaleX = canvasWidth / sourceWidth
      const scaleY = canvasHeight / sourceHeight
      canvas.width = canvasWidth
      canvas.height = canvasHeight
      const styleWidth = canvasWidth / dpr
      const styleHeight = canvasHeight / dpr
      // canvas元素实际上的大小
      canvas.style.width = styleWidth + 'px'
      canvas.style.height = styleHeight + 'px'
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('浏览器无法创建导出画布，请使用 SVG 或 JSON 导出。')
      ctx.scale(dpr, dpr)
      // 绘制背景
      if (!transparent) {
        await this.drawBackgroundToCanvas(ctx, styleWidth, styleHeight)
        throwIfExportAborted(signal)
      }
      // 图片绘制到canvas里
      // 如果有裁减数据，那么需要进行裁减
      const fitBgLeft =
        (fitBgImgWidth > 0 ? (fitBgImgWidth - imgWidth) / 2 : 0) * scaleX
      const fitBgTop =
        (fitBgImgHeight > 0 ? (fitBgImgHeight - imgHeight) / 2 : 0) * scaleY
      if (clipData) {
        ctx.drawImage(
          img,
          clipData.left,
          clipData.top,
          clipData.width,
          clipData.height,
          paddingX * scaleX + fitBgLeft,
          paddingY * scaleY + fitBgTop,
          clipData.width * scaleX,
          clipData.height * scaleY
        )
      } else {
        ctx.drawImage(
          img,
          fitBgLeft,
          fitBgTop,
          imgWidth * scaleX,
          imgHeight * scaleY
        )
      }
      const dataUrl = canvas.toDataURL(format)
      if (typeof dataUrl !== 'string' || !/^data:image\/[\w.+-]+;base64,.+/i.test(dataUrl)) {
        throw new Error('浏览器未生成有效图片，请使用 SVG 或 JSON 导出。')
      }
      throwIfExportAborted(signal)
      return dataUrl
    } finally {
      signal?.removeEventListener('abort', release)
      release()
    }
  }

  //  在canvas上绘制思维导图背景
  drawBackgroundToCanvas(ctx, width, height) {
    return new Promise((resolve, reject) => {
      const {
        backgroundColor = '#fff',
        backgroundImage,
        backgroundRepeat = 'no-repeat',
        backgroundPosition = 'center center',
        backgroundSize = 'cover'
      } = this.exportTheme || this.mindMap.themeConfig
      // 背景颜色
      ctx.save()
      ctx.rect(0, 0, width, height)
      ctx.fillStyle = backgroundColor
      ctx.fill()
      ctx.restore()
      // 背景图片
      if (backgroundImage && backgroundImage !== 'none') {
        ctx.save()
        drawBackgroundImageToCanvas(
          ctx,
          width,
          height,
          backgroundImage,
          {
            backgroundRepeat,
            backgroundPosition,
            backgroundSize
          },
          err => {
            if (err) {
              reject(err)
            } else {
              resolve()
            }
            if (!this.exportSession?.signal.aborted) ctx.restore()
          },
          { signal: this.exportSession?.signal }
        )
      } else {
        resolve()
      }
    })
  }

  //  在svg上绘制思维导图背景
  async drawBackgroundToSvg(svg) {
    const {
      backgroundColor = '#fff',
      backgroundImage,
      backgroundRepeat = 'repeat'
    } = this.exportTheme || this.mindMap.themeConfig
    svg.css('background-color', backgroundColor)
    if (backgroundImage && backgroundImage !== 'none') {
      try {
        const imgDataUrl = await imgToDataUrl(backgroundImage, false, { signal: this.exportSession?.signal })
        throwIfExportAborted(this.exportSession?.signal)
        svg.css('background-image', `url(${imgDataUrl})`)
        svg.css('background-repeat', backgroundRepeat)
      } catch (error) {
        throwIfExportAborted(this.exportSession?.signal)
        throw new Error('背景图片无法加载，已取消导出。请检查图片地址或改用 JSON 备份。', { cause: error })
      }
    }
  }

  // 导出为指定格式的图片
  async _image(format, name, transparent = false, node = null, fitBg = false) {
    this.mindMap.renderer.textEdit.hideEditTextBox()
    this.handleNodeExport(node)
    const { str, clipData } = await this.getSvgData(node)
    const svgUrl = await this.fixSvgStrAndToBlob(str)
    const res = await this.svgToPng(
      svgUrl,
      transparent,
      clipData,
      fitBg,
      format
    )
    return res
  }

  //  导出为png
  /**
   * 方法1.把svg的图片都转化成data:url格式，再转换
   * 方法2.把svg的图片提取出来再挨个绘制到canvas里，最后一起转换
   */
  async png(...args) {
    const res = await this._image('image/png', ...args)
    return res
  }

  // 导出为jpg
  async jpg(...args) {
    const res = await this._image('image/jpg', ...args)
    return res
  }

  // 导出指定节点，如果该节点是激活状态，那么取消激活和隐藏展开收起按钮
  handleNodeExport(node) {
    if (node && node.getData('isActive')) {
      node.deactivate()
      const { alwaysShowExpandBtn, notShowExpandBtn } = this.mindMap.opt
      if (!alwaysShowExpandBtn && !notShowExpandBtn && node.getData('expand')) {
        node.removeExpandBtn()
      }
    }
  }

  //  导出为pdf
  async pdf(name, transparent = false, fitBg = false) {
    if (!this.mindMap.doExportPDF) {
      throw new Error('请注册ExportPDF插件')
    }
    const img = await this.png(name, transparent, null, fitBg)
    // 使用jspdf库
    // await this.mindMap.doExportPDF.pdf(name, img)
    // 使用pdf-lib库
    throwIfExportAborted(this.exportSession?.signal)
    const res = await abortableExport(this.mindMap.doExportPDF.pdf(img, {
      signal: this.exportSession?.signal
    }), this.exportSession?.signal)
    return res
  }

  // 导出为xmind
  async xmind(name) {
    if (!this.mindMap.doExportXMind) {
      throw new Error('请注册ExportXMind插件')
    }
    const data = this.mindMap.getData()
    const blob = await abortableExport(this.mindMap.doExportXMind.xmind(data, name, {
      signal: this.exportSession?.signal
    }), this.exportSession?.signal)
    const res = await readBlob(blob, { signal: this.exportSession?.signal })
    return res
  }

  //  导出为svg
  async svg(name) {
    this.mindMap.renderer.textEdit.hideEditTextBox()
    const { node } = await this.getSvgData()
    throwIfExportAborted(this.exportSession?.signal)
    addSafeSvgTitle(node, name, { prepend: true })
    await this.drawBackgroundToSvg(node)
    const str = node.svg()
    const res = await this.fixSvgStrAndToBlob(str)
    return res
  }

  // 修复svg字符串，并且转换为blob数据
  async fixSvgStrAndToBlob(str) {
    throwIfExportAborted(this.exportSession?.signal)
    // 移除字符串中的html实体
    str = removeHTMLEntities(str)
    // 给html自闭合标签添加闭合状态
    str = handleSelfCloseTags(str)
    // 转换成blob数据
    const blob = new Blob([str], {
      type: 'image/svg+xml'
    })
    const res = await readBlob(blob, { signal: this.exportSession?.signal })
    return res
  }

  //  导出为json
  async json(name, withConfig = true, documentSnapshot = null) {
    const data = withConfig && documentSnapshot?.root
      ? documentSnapshot
      : this.mindMap.getData(withConfig)
    const str = stringifyJsonValueIterative(data)
    return new Blob([str], { type: 'application/json' })
  }

  //  专有文件，其实就是json文件
  async smm(name, withConfig, documentSnapshot) {
    return await this.json(name, withConfig, documentSnapshot)
  }

  // markdown文件
  async md() {
    const data = this.mindMap.getData()
    const { transformToMarkdown } = await import('../parse/toMarkdown')
    throwIfExportAborted(this.exportSession?.signal)
    const content = transformToMarkdown(data)
    return new Blob([content], { type: 'text/markdown' })
  }

  // txt文件
  async txt() {
    const data = this.mindMap.getData()
    const { transformToTxt } = await import('../parse/toTxt')
    throwIfExportAborted(this.exportSession?.signal)
    const content = transformToTxt(data)
    return new Blob([content], { type: 'text/plain' })
  }
}

Export.instanceName = 'doExport'

export default Export
