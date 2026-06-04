import { CONSTANTS } from '../../constants/constant'

//  视图操作类
class View {
  //  构造函数
  constructor(opt = {}) {
    this.opt = opt
    this.mindMap = this.opt.mindMap
    this.scale = 1
    this.sx = 0
    this.sy = 0
    this.x = 0
    this.y = 0
    this.firstDrag = true
    this.setTransformData(this.mindMap.opt.viewData)
    this.bind()
  }

  //  绑定
  bind() {
    // 快捷键
    this.mindMap.keyCommand.addShortcut('Control+=', () => {
      this.enlarge()
    })
    this.mindMap.keyCommand.addShortcut('Control+-', () => {
      this.narrow()
    })
    this.mindMap.keyCommand.addShortcut('Control+i', () => {
      this.fit()
    })
    // 拖动视图
    this.mindMap.event.on('mousedown', e => {
      const { isDisableDrag, mousedownEventPreventDefault } = this.mindMap.opt
      if (isDisableDrag) return
      if (mousedownEventPreventDefault) {
        e.preventDefault()
      }
      this.sx = this.x
      this.sy = this.y
    })
    this.mindMap.event.on('drag', (e, event) => {
      // 按住ctrl键拖动为多选
      // 禁用拖拽
      if (e.ctrlKey || e.metaKey || this.mindMap.opt.isDisableDrag) {
        return
      }
      if (this.firstDrag) {
        this.firstDrag = false
        // 清除激活节点
        if (this.mindMap.renderer.activeNodeList.length > 0) {
          this.mindMap.execCommand('CLEAR_ACTIVE_NODE')
        }
      }
      this.x = this.sx + event.mousemoveOffset.x
      this.y = this.sy + event.mousemoveOffset.y
      this.transform()
    })
    this.mindMap.event.on('mouseup', () => {
      this.firstDrag = true
    })
    // 放大缩小视图
    this.mindMap.event.on('mousewheel', (e, dirs, event, isTouchPad) => {
      const {
        customHandleMousewheel,
        mousewheelAction,
        mouseScaleCenterUseMousePosition,
        mousewheelMoveStep,
        mousewheelZoomActionReverse,
        disableMouseWheelZoom,
        translateRatio
      } = this.mindMap.opt
      // 是否自定义鼠标滚轮事件
      if (
        customHandleMousewheel &&
        typeof customHandleMousewheel === 'function'
      ) {
        return customHandleMousewheel(e)
      }
      // 1.鼠标滚轮事件控制缩放
      if (
        mousewheelAction === CONSTANTS.MOUSE_WHEEL_ACTION.ZOOM ||
        e.ctrlKey ||
        e.metaKey
      ) {
        if (disableMouseWheelZoom) return
        const { x: clientX, y: clientY } = this.mindMap.toPos(
          e.clientX,
          e.clientY
        )
        const cx = mouseScaleCenterUseMousePosition ? clientX : undefined
        const cy = mouseScaleCenterUseMousePosition ? clientY : undefined
        // 如果来自触控板，那么过滤掉左右的移动
        if (
          isTouchPad &&
          (dirs.includes(CONSTANTS.DIR.LEFT) ||
            dirs.includes(CONSTANTS.DIR.RIGHT))
        ) {
          dirs = dirs.filter(dir => {
            return ![CONSTANTS.DIR.LEFT, CONSTANTS.DIR.RIGHT].includes(dir)
          })
        }
        switch (true) {
          // 鼠标滚轮，向上和向左，都是缩小
          case dirs.includes(CONSTANTS.DIR.UP || CONSTANTS.DIR.LEFT):
            mousewheelZoomActionReverse
              ? this.enlarge(cx, cy, isTouchPad)
              : this.narrow(cx, cy, isTouchPad)
            break
          // 鼠标滚轮，向下和向右，都是放大
          case dirs.includes(CONSTANTS.DIR.DOWN || CONSTANTS.DIR.RIGHT):
            mousewheelZoomActionReverse
              ? this.narrow(cx, cy, isTouchPad)
              : this.enlarge(cx, cy, isTouchPad)
            break
        }
      } else {
        // 2.鼠标滚轮事件控制画布移动
        let stepX = 0
        let stepY = 0
        if (isTouchPad) {
          // 如果是触控板，那么直接使用触控板滑动距离
          stepX = Math.abs(e.wheelDeltaX)
          stepY = Math.abs(e.wheelDeltaY)
        } else {
          stepX = stepY = mousewheelMoveStep
        }
        let mx = 0
        let my = 0
        // 上移
        if (dirs.includes(CONSTANTS.DIR.DOWN)) {
          my = -stepY
        }
        // 下移
        if (dirs.includes(CONSTANTS.DIR.UP)) {
          my = stepY
        }
        // 右移
        if (dirs.includes(CONSTANTS.DIR.LEFT)) {
          mx = stepX
        }
        // 左移
        if (dirs.includes(CONSTANTS.DIR.RIGHT)) {
          mx = -stepX
        }
        this.translateXY(mx * translateRatio, my * translateRatio)
      }
    })
    this.mindMap.on('resize', () => {
      if (!this.checkNeedMindMapInCanvas()) return
      this.transform()
    })
  }

  //  获取当前变换状态数据
  getTransformData() {
    return {
      transform: this.mindMap.draw.transform(),
      state: {
        scale: this.scale,
        x: this.x,
        y: this.y,
        sx: this.sx,
        sy: this.sy
      }
    }
  }

  //  动态设置变换状态数据
  setTransformData(viewData) {
    if (viewData) {
      Object.keys(viewData.state).forEach(prop => {
        this[prop] = viewData.state[prop]
      })
      this.transform()
      this.emitEvent('scale')
      this.emitEvent('translate')
    }
  }

  //  平移x,y方向
  translateXY(x, y) {
    if (x === 0 && y === 0) return
    this.x += x
    this.y += y
    this.transform()
    this.emitEvent('translate')
  }

  //  平移x方向
  translateX(step) {
    if (step === 0) return
    this.x += step
    this.transform()
    this.emitEvent('translate')
  }

  //  平移x方式到
  translateXTo(x) {
    this.x = x
    this.transform()
    this.emitEvent('translate')
  }

  //  平移y方向
  translateY(step) {
    if (step === 0) return
    this.y += step
    this.transform()
    this.emitEvent('translate')
  }

  //  平移y方向到
  translateYTo(y) {
    this.y = y
    this.transform()
    this.emitEvent('translate')
  }

  //   应用变换
  transform() {
    try {
      this.limitMindMapInCanvas()
    } catch (error) {
      console.warn('[MindMap] limitMindMapInCanvas error:', error)
    }
    this.mindMap.draw.transform({
      origin: [0, 0],
      scale: this.scale,
      translate: [this.x, this.y]
    })
    // 记录已应用的变换值，供下一帧 limitMindMapInCanvas 反推坐标使用
    this._appliedX = this.x
    this._appliedY = this.y
    this._appliedScale = this.scale
    this.mindMap.emit('view_data_change', this.getTransformData())
  }

  //  恢复
  reset() {
    const scaleChange = this.scale !== 1
    const translateChange = this.x !== 0 || this.y !== 0
    this.scale = 1
    this.x = 0
    this.y = 0
    this.transform()
    if (scaleChange) {
      this.emitEvent('scale')
    }
    if (translateChange) {
      this.emitEvent('translate')
    }
  }

  //  缩小
  narrow(cx, cy, isTouchPad) {
    let { scaleRatio, minZoomRatio } = this.mindMap.opt
    scaleRatio = scaleRatio / (isTouchPad ? 5 : 1)
    const scale = Math.max(this.scale - scaleRatio, minZoomRatio / 100)
    this.scaleInCenter(scale, cx, cy)
    this.transform()
    this.emitEvent('scale')
  }

  //  放大
  enlarge(cx, cy, isTouchPad) {
    let { scaleRatio, maxZoomRatio } = this.mindMap.opt
    scaleRatio = scaleRatio / (isTouchPad ? 5 : 1)
    let scale = 0
    if (maxZoomRatio === -1) {
      scale = this.scale + scaleRatio
    } else {
      scale = Math.min(this.scale + scaleRatio, maxZoomRatio / 100)
    }
    this.scaleInCenter(scale, cx, cy)
    this.transform()
    this.emitEvent('scale')
  }

  // 基于指定中心进行缩放，cx，cy 可不指定，此时会使用画布中心点
  scaleInCenter(scale, cx, cy) {
    if (cx === undefined || cy === undefined) {
      cx = this.mindMap.width / 2
      cy = this.mindMap.height / 2
    }
    const prevScale = this.scale
    const ratio = 1 - scale / prevScale
    const dx = (cx - this.x) * ratio
    const dy = (cy - this.y) * ratio
    this.x += dx
    this.y += dy
    this.scale = scale
  }

  //  设置缩放
  setScale(scale, cx, cy) {
    if (cx !== undefined && cy !== undefined) {
      this.scaleInCenter(scale, cx, cy)
    } else {
      this.scale = scale
    }
    this.transform()
    this.emitEvent('scale')
  }

  // 适应画布大小
  fit(getRbox = () => {}, enlarge = false, fitPadding) {
    fitPadding =
      fitPadding === undefined ? this.mindMap.opt.fitPadding : fitPadding
    const draw = this.mindMap.draw
    const origTransform = draw.transform()
    const rect = getRbox() || draw.rbox()
    const drawWidth = rect.width / origTransform.scaleX
    const drawHeight = rect.height / origTransform.scaleY
    const drawRatio = drawWidth / drawHeight
    let { width: elWidth, height: elHeight } = this.mindMap.elRect
    elWidth = elWidth - fitPadding * 2
    elHeight = elHeight - fitPadding * 2
    const elRatio = elWidth / elHeight
    let newScale = 0
    let flag = ''
    if (drawWidth <= elWidth && drawHeight <= elHeight && !enlarge) {
      newScale = 1
      flag = 1
    } else {
      let newWidth = 0
      let newHeight = 0
      if (drawRatio > elRatio) {
        newWidth = elWidth
        newHeight = elWidth / drawRatio
        flag = 2
      } else {
        newHeight = elHeight
        newWidth = elHeight * drawRatio
        flag = 3
      }
      newScale = newWidth / drawWidth
    }
    this.setScale(newScale)
    const newRect = getRbox() || draw.rbox()
    // 需要考虑画布容器距浏览器窗口左上角的距离
    newRect.x -= this.mindMap.elRect.left
    newRect.y -= this.mindMap.elRect.top
    let newX = 0
    let newY = 0
    if (flag === 1) {
      newX = -newRect.x + fitPadding + (elWidth - newRect.width) / 2
      newY = -newRect.y + fitPadding + (elHeight - newRect.height) / 2
    } else if (flag === 2) {
      newX = -newRect.x + fitPadding
      newY = -newRect.y + fitPadding + (elHeight - newRect.height) / 2
    } else if (flag === 3) {
      newX = -newRect.x + fitPadding + (elWidth - newRect.width) / 2
      newY = -newRect.y + fitPadding
    }
    this.translateXY(newX, newY)
  }

  // 判断是否需要将思维导图限制在画布内
  checkNeedMindMapInCanvas() {
    // 如果当前在演示模式，那么不需要限制
    if (this.mindMap.demonstrate && this.mindMap.demonstrate.isInDemonstrate) {
      return false
    }
    const { isLimitMindMapInCanvasWhenHasScrollbar, isLimitMindMapInCanvas } =
      this.mindMap.opt
    // 如果注册了滚动条插件，那么使用isLimitMindMapInCanvasWhenHasScrollbar配置
    if (this.mindMap.scrollbar) {
      return isLimitMindMapInCanvasWhenHasScrollbar
    } else {
      // 否则使用isLimitMindMapInCanvas配置
      return isLimitMindMapInCanvas
    }
  }

  // 将思维导图限制在画布内
  // 设计原则：无论缩放级别，至少保证脑图有小部分（80px）可见于画布中
  limitMindMapInCanvas() {
    if (!this.checkNeedMindMapInCanvas()) return

    const draw = this.mindMap.draw
    const drawRect = draw.rbox()
    const elRect = this.mindMap.elRect

    // 安全检查：初始化阶段绘制区域或容器信息可能尚未就绪
    if (!drawRect || !drawRect.width || !elRect) return

    // ---- 第一步：将 rbox 转为容器相对坐标 ----
    // rbox() 返回文档绝对坐标，减去容器偏移量得到容器相对坐标
    // 这与 fit()、Scrollbar、MiniMap 中的处理方式一致
    const prevX = this._appliedX ?? this.x
    const prevY = this._appliedY ?? this.y
    const prevScale = this._appliedScale ?? this.scale

    // draw.rbox() 是上一帧变换的结果，需要用上一帧的 this.x/y/scale 来反推
    const screenLeft = drawRect.x - elRect.left
    const screenTop = drawRect.y - elRect.top

    // ---- 第二步：反推脑图在内部坐标系下的固有位置 ----
    // 上一帧：screenLeft = intLeft × prevScale + prevX
    // 反推：  intLeft = (screenLeft - prevX) / prevScale
    const intLeft = (screenLeft - prevX) / prevScale
    const intTop = (screenTop - prevY) / prevScale
    const intW = drawRect.width / prevScale
    const intH = drawRect.height / prevScale

    // ---- 第三步：用新的 this.x/y/scale 正推屏幕坐标 ----
    // newScreenLeft = intLeft × this.scale + this.x
    const newLeft = intLeft * this.scale + this.x
    const newTop = intTop * this.scale + this.y
    const newRight = newLeft + intW * this.scale
    const newBottom = newTop + intH * this.scale

    // ---- 第四步：约束 —— 脑图不能完全离开画布 ----
    // 至少保证 minVisible 像素的脑图内容可见于画布中
    const canvasW = this.mindMap.width
    const canvasH = this.mindMap.height
    const minVisible = 80

    // 向右拖：脑图左边不能超过 (画布右边 - minVisible)
    //   newLeft < canvasW - minVisible
    //   x < canvasW - minVisible - intLeft × scale
    const maxX = canvasW - minVisible - intLeft * this.scale

    // 向左拖：脑图右边不能低于 (画布左边 + minVisible)
    //   newRight > minVisible
    //   x > minVisible - (intLeft + intW) × scale
    const minX = minVisible - (intLeft + intW) * this.scale

    // 同理 Y 轴
    const maxY = canvasH - minVisible - intTop * this.scale
    const minY = minVisible - (intTop + intH) * this.scale

    // ---- 第五步：钳制 ----
    if (minX <= maxX) {
      if (this.x > maxX) this.x = maxX
      if (this.x < minX) this.x = minX
    }
    if (minY <= maxY) {
      if (this.y > maxY) this.y = maxY
      if (this.y < minY) this.y = minY
    }
  }

  // 派发事件
  emitEvent(type) {
    switch (type) {
      case 'scale':
        this.mindMap.emit('scale', this.scale)
        break
      case 'translate':
        this.mindMap.emit('translate', this.x, this.y)
        break
    }
  }
}

export default View
