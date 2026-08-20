import { CONSTANTS } from '../../constants/constant'
import { resolveWheelZoomDirection } from '../../utils/wheel'
import {
  calculateViewFit,
  calculateViewScaleAroundPoint,
  normalizeViewCoordinate,
  normalizeViewScale,
  normalizeViewTransformData
} from '../../utils/viewState'

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

    // 节流控制：限制 limitMindMapInCanvas 的调用频率
    this._lastLimitCheck = 0
    this._limitThrottleMs = this.mindMap.opt.limitThrottleMs ?? 16 // 默认 ~60fps

    this.setTransformData(this.mindMap.opt.viewData)
    this.bind()
  }

  //  绑定
  bind() {
    // 保存事件处理函数引用，用于 unbind
    this._handlers = {}

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
    this._handlers.mousedown = e => {
      const { isDisableDrag, mousedownEventPreventDefault } = this.mindMap.opt
      if (isDisableDrag) return
      if (mousedownEventPreventDefault) {
        e.preventDefault()
      }
      this.sx = this.x
      this.sy = this.y
    }
    this.mindMap.event.on('mousedown', this._handlers.mousedown)

    this._handlers.drag = (e, event) => {
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
    }
    this.mindMap.event.on('drag', this._handlers.drag)

    this._handlers.mouseup = () => {
      this.firstDrag = true
    }
    this.mindMap.event.on('mouseup', this._handlers.mouseup)
    // 放大缩小视图
    this._handlers.mousewheel = (e, dirs, event, isTouchPad) => {
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
        const direction = resolveWheelZoomDirection(dirs)
        if (direction < 0) {
          mousewheelZoomActionReverse
            ? this.enlarge(cx, cy, isTouchPad)
            : this.narrow(cx, cy, isTouchPad)
        } else if (direction > 0) {
          mousewheelZoomActionReverse
            ? this.narrow(cx, cy, isTouchPad)
            : this.enlarge(cx, cy, isTouchPad)
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
    }
    this.mindMap.event.on('mousewheel', this._handlers.mousewheel)

    this._handlers.resize = () => {
      if (!this.checkNeedMindMapInCanvas()) return
      this.transform()
    }
    this.mindMap.on('resize', this._handlers.resize)
  }

  //  解绑事件（防止内存泄漏）
  unbind() {
    if (this._handlers) {
      this.mindMap.event.off('mousedown', this._handlers.mousedown)
      this.mindMap.event.off('drag', this._handlers.drag)
      this.mindMap.event.off('mouseup', this._handlers.mouseup)
      this.mindMap.event.off('mousewheel', this._handlers.mousewheel)
      this.mindMap.off('resize', this._handlers.resize)
      this._handlers = null
    }
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
    const normalized = normalizeViewTransformData(viewData, this)
    if (!normalized) return false

    const { scale, x, y, sx, sy } = normalized.state
    this.scale = scale
    this.x = x
    this.y = y
    this.sx = sx
    this.sy = sy
    this.mindMap.draw.transform(normalized.transform)
    this._appliedX = x
    this._appliedY = y
    this._appliedScale = scale
    this.mindMap.emit('view_data_change', this.getTransformData())
    this.emitEvent('scale')
    this.emitEvent('translate')
    return true
  }

  //  平移x,y方向
  translateXY(x, y) {
    // 参数验证：防止 NaN 或 Infinity
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[MindMap] translateXY: invalid parameters', { x, y })
      }
      return
    }
    if (x === 0 && y === 0) return
    this.x += x
    this.y += y
    this.transform()
    this.emitEvent('translate')
  }

  //  平移x方向
  translateX(step) {
    if (!Number.isFinite(step)) {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[MindMap] translateX: invalid parameter', step)
      }
      return
    }
    if (step === 0) return
    this.x += step
    this.transform()
    this.emitEvent('translate')
  }

  //  平移x方式到
  translateXTo(x) {
    if (!Number.isFinite(x)) {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[MindMap] translateXTo: invalid parameter', x)
      }
      return
    }
    this.x = x
    this.transform()
    this.emitEvent('translate')
  }

  //  平移y方向
  translateY(step) {
    if (!Number.isFinite(step)) {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[MindMap] translateY: invalid parameter', step)
      }
      return
    }
    if (step === 0) return
    this.y += step
    this.transform()
    this.emitEvent('translate')
  }

  //  平移y方向到
  translateYTo(y) {
    if (!Number.isFinite(y)) {
      if (process.env.NODE_ENV === 'development') {
        console.warn('[MindMap] translateYTo: invalid parameter', y)
      }
      return
    }
    this.y = y
    this.transform()
    this.emitEvent('translate')
  }

  //   应用变换
  transform() {
    // 重入锁：防止 transform → emit → listener → transform 的递归死循环
    if (this._transforming) return
    this._transforming = true

    try {
      this.limitMindMapInCanvas()

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
    } catch (error) {
      console.warn('[MindMap] transform error:', error)
    } finally {
      this._transforming = false
    }
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
    const nextScale = normalizeViewScale(scale)
    if (nextScale === null) return false
    const defaultCenterX = normalizeViewCoordinate(this.mindMap.width) / 2
    const defaultCenterY = normalizeViewCoordinate(this.mindMap.height) / 2
    const centerX = Number.isFinite(Number(cx))
      ? Number(cx)
      : defaultCenterX
    const centerY = Number.isFinite(Number(cy))
      ? Number(cy)
      : defaultCenterY
    const nextState = calculateViewScaleAroundPoint(
      this,
      nextScale,
      { x: centerX, y: centerY }
    )
    if (!nextState) return false
    this.x = nextState.x
    this.y = nextState.y
    this.scale = nextState.scale
    return true
  }

  //  设置缩放
  setScale(scale, cx, cy) {
    const nextScale = normalizeViewScale(scale)
    if (nextScale === null) return false
    const previousScale = this.scale
    const previousX = this.x
    const previousY = this.y
    this.x = normalizeViewCoordinate(this.x)
    this.y = normalizeViewCoordinate(this.y)
    if (cx !== undefined && cy !== undefined) {
      if (!this.scaleInCenter(nextScale, cx, cy)) return false
    } else {
      this.scale = nextScale
    }
    if (
      this.scale === previousScale
      && this.x === previousX
      && this.y === previousY
    ) {
      return false
    }
    this.transform()
    this.emitEvent('scale')
    return true
  }

  // 适应画布大小
  fit(getRbox = () => {}, enlarge = false, fitPadding) {
    fitPadding =
      fitPadding === undefined ? this.mindMap.opt.fitPadding : fitPadding
    const draw = this.mindMap.draw
    let rect = null
    let transform = null
    try {
      transform = draw.transform()
      rect = getRbox() || draw.rbox()
    } catch {
      return false
    }
    const fit = calculateViewFit({
      contentRect: rect,
      viewportRect: this.mindMap.elRect,
      transform,
      state: this,
      padding: fitPadding,
      enlarge
    })
    if (!fit) return false

    this.setScale(fit.scale)
    this.translateXY(fit.offsetX, fit.offsetY)
    return true
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
  // 设计原则：无论缩放级别，至少保证脑图有小部分可见于画布中
  limitMindMapInCanvas() {
    if (!this.checkNeedMindMapInCanvas()) return

    const draw = this.mindMap.draw
    const elRect = this.mindMap.elRect
    if (!elRect) return

    // ---- 节流控制 draw.rbox() DOM 查询 ----
    // 仅节流昂贵的 DOM 查询，边界钳制数学计算每次都执行（避免抖动）
    const now = performance.now()
    if (now - this._lastLimitCheck >= this._limitThrottleMs) {
      this._lastLimitCheck = now

      try {
        const drawRect = draw.rbox()
        if (!drawRect || !drawRect.width || !drawRect.height) return

        const prevX = this._appliedX ?? this.x
        const prevY = this._appliedY ?? this.y
        const prevScale = this._appliedScale ?? this.scale

        if (!prevScale || !Number.isFinite(prevScale)) return

        // rbox() 转为容器相对坐标
        const screenLeft = drawRect.x - elRect.left
        const screenTop = drawRect.y - elRect.top

        // 反推脑图内部固有坐标（缓存，节流期间复用）
        const intLeft = (screenLeft - prevX) / prevScale
        const intTop = (screenTop - prevY) / prevScale
        const intW = drawRect.width / prevScale
        const intH = drawRect.height / prevScale

        if (Number.isFinite(intLeft) && Number.isFinite(intW) && intW > 0) {
          this._cachedBounds = { intLeft, intTop, intW, intH }
        }
      } catch (e) {
        // rbox() 可能在 SVG 未就绪时抛异常，安全忽略
        return
      }
    }

    // 没有缓存数据，跳过钳制
    if (!this._cachedBounds) return

    const { intLeft, intTop, intW, intH } = this._cachedBounds
    if (!Number.isFinite(this.scale) || this.scale <= 0) return

    const canvasW = this.mindMap.width
    const canvasH = this.mindMap.height
    if (!canvasW || !canvasH) return
    const minVisible = this.mindMap.opt.minVisibleInCanvas ?? 80

    // 计算 x/y 约束范围
    const maxX = canvasW - minVisible - intLeft * this.scale
    const minX = minVisible - (intLeft + intW) * this.scale
    const maxY = canvasH - minVisible - intTop * this.scale
    const minY = minVisible - (intTop + intH) * this.scale

    if (!Number.isFinite(maxX) || !Number.isFinite(minX)) return

    // 钳制
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
