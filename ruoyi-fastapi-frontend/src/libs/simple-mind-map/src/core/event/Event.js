import EventEmitter from 'eventemitter3'
import { CONSTANTS } from '../../constants/constant'
import { isLikelyTouchpadWheel } from '../../utils/wheel'

//  事件类
class Event extends EventEmitter {
  //  构造函数
  constructor(opt = {}) {
    super()
    this.opt = opt
    this.mindMap = opt.mindMap
    this.isLeftMousedown = false
    this.isRightMousedown = false
    this.isMiddleMousedown = false
    this.mousedownPos = {
      x: 0,
      y: 0
    }
    this.mousemovePos = {
      x: 0,
      y: 0
    }
    this.mousemoveOffset = {
      x: 0,
      y: 0
    }
    this.bindFn()
    this.bind()
  }

  //  绑定函数上下文
  bindFn() {
    this.onBodyMousedown = this.onBodyMousedown.bind(this)
    this.onBodyClick = this.onBodyClick.bind(this)
    this.onDrawClick = this.onDrawClick.bind(this)
    this.onMousedown = this.onMousedown.bind(this)
    this._onMousemoveRaw = this.onMousemove.bind(this)
    this.onMousemove = this._throttleRAF(this._onMousemoveRaw)
    this.onMouseup = this.onMouseup.bind(this)
    this.onNodeMouseup = this.onNodeMouseup.bind(this)
    this._onMousewheelRaw = this.onMousewheel.bind(this)
    this.onMousewheel = this._throttleWheelRAF(this._onMousewheelRaw)
    this.onContextmenu = this.onContextmenu.bind(this)
    this.onSvgMousedown = this.onSvgMousedown.bind(this)
    this.onKeyup = this.onKeyup.bind(this)
    this.onMouseenter = this.onMouseenter.bind(this)
    this.onMouseleave = this.onMouseleave.bind(this)
  }

  _throttleRAF(fn) {
    let ticking = false
    return function (...args) {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        fn.apply(this, args)
        ticking = false
      })
    }
  }

  _throttleWheelRAF(fn) {
    let ticking = false
    return function (e) {
      e.stopPropagation()
      e.preventDefault()
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        fn.call(this, e)
        ticking = false
      })
    }
  }

  //  绑定事件
  bind() {
    document.body.addEventListener('mousedown', this.onBodyMousedown)
    document.body.addEventListener('click', this.onBodyClick)
    this.mindMap.svg.on('click', this.onDrawClick)
    this.mindMap.el.addEventListener('mousedown', this.onMousedown)
    this.mindMap.svg.on('mousedown', this.onSvgMousedown)
    window.addEventListener('mousemove', this.onMousemove)
    window.addEventListener('mouseup', this.onMouseup)
    this.on('node_mouseup', this.onNodeMouseup)
    this.mindMap.el.addEventListener('wheel', this.onMousewheel, { passive: false })
    this.mindMap.svg.on('contextmenu', this.onContextmenu)
    this.mindMap.svg.on('mouseenter', this.onMouseenter)
    this.mindMap.svg.on('mouseleave', this.onMouseleave)
    window.addEventListener('keyup', this.onKeyup)
  }

  //  解绑事件
  unbind() {
    document.body.removeEventListener('mousedown', this.onBodyMousedown)
    document.body.removeEventListener('click', this.onBodyClick)
    this.mindMap.svg.off('click', this.onDrawClick)
    this.mindMap.el.removeEventListener('mousedown', this.onMousedown)
    this.mindMap.svg.off('mousedown', this.onSvgMousedown)
    window.removeEventListener('mousemove', this.onMousemove)
    window.removeEventListener('mouseup', this.onMouseup)
    this.off('node_mouseup', this.onNodeMouseup)
    this.mindMap.el.removeEventListener('wheel', this.onMousewheel, { passive: false })
    this.mindMap.svg.off('contextmenu', this.onContextmenu)
    this.mindMap.svg.off('mouseenter', this.onMouseenter)
    this.mindMap.svg.off('mouseleave', this.onMouseleave)
    window.removeEventListener('keyup', this.onKeyup)
  }

  //   画布的单击事件
  onDrawClick(e) {
    this.emit('draw_click', e)
  }

  // 页面的鼠标按下事件
  onBodyMousedown(e) {
    this.emit('body_mousedown', e)
  }

  // 页面的单击事件
  onBodyClick(e) {
    this.emit('body_click', e)
  }

  //   svg画布的鼠标按下事件
  onSvgMousedown(e) {
    this.emit('svg_mousedown', e)
  }

  //  鼠标按下事件
  onMousedown(e) {
    // 鼠标左键
    if (e.which === 1) {
      this.isLeftMousedown = true
    } else if (e.which === 3) {
      this.isRightMousedown = true
    } else if (e.which === 2) {
      this.isMiddleMousedown = true
    }
    this.mousedownPos.x = e.clientX
    this.mousedownPos.y = e.clientY
    this.emit('mousedown', e, this)
  }

  //  鼠标移动事件
  onMousemove(e) {
    let { useLeftKeySelectionRightKeyDrag } = this.mindMap.opt
    this.mousemovePos.x = e.clientX
    this.mousemovePos.y = e.clientY
    this.mousemoveOffset.x = e.clientX - this.mousedownPos.x
    this.mousemoveOffset.y = e.clientY - this.mousedownPos.y
    this.emit('mousemove', e, this)
    if (
      this.isMiddleMousedown ||
      (useLeftKeySelectionRightKeyDrag
        ? this.isRightMousedown
        : this.isLeftMousedown)
    ) {
      e.preventDefault()
      this.emit('drag', e, this)
    }
  }

  //  鼠标松开事件
  onMouseup(e) {
    this.onNodeMouseup()
    this.emit('mouseup', e, this)
  }

  // 节点鼠标松开事件
  onNodeMouseup() {
    this.isLeftMousedown = false
    this.isRightMousedown = false
    this.isMiddleMousedown = false
  }

  //  鼠标滚动/触控板滑动
  onMousewheel(e) {
    const dirs = []
    if (e.deltaY < 0) dirs.push(CONSTANTS.DIR.UP)
    if (e.deltaY > 0) dirs.push(CONSTANTS.DIR.DOWN)
    if (e.deltaX < 0) dirs.push(CONSTANTS.DIR.LEFT)
    if (e.deltaX > 0) dirs.push(CONSTANTS.DIR.RIGHT)
    // 判断是否是触控板
    let isTouchPad = false
    const { customCheckIsTouchPad } = this.mindMap.opt
    if (typeof customCheckIsTouchPad === 'function') {
      isTouchPad = Boolean(customCheckIsTouchPad(e))
    } else {
      isTouchPad = isLikelyTouchpadWheel(e)
    }
    this.emit('mousewheel', e, dirs, this, isTouchPad)
  }

  //  鼠标右键菜单事件
  onContextmenu(e) {
    e.preventDefault()
    // Mac上按住ctrl键点击鼠标左键不知为何触发的是contextmenu事件
    if (e.ctrlKey) return
    this.emit('contextmenu', e)
  }

  //  按键松开事件
  onKeyup(e) {
    this.emit('keyup', e)
  }

  // 进入
  onMouseenter(e) {
    this.emit('svg_mouseenter', e)
  }

  // 离开
  onMouseleave(e) {
    this.emit('svg_mouseleave', e)
  }
}

export default Event
