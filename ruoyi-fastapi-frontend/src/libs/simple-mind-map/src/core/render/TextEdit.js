import {
  getStrWithBrFromHtml,
  checkNodeOuter,
  focusInput,
  selectAllInput,
  htmlEscape,
  handleInputPasteText,
  checkSmmFormatData,
  getTextFromHtml,
  isWhite,
  getVisibleColorFromTheme
} from '../../utils'
import {
  ERROR_TYPES,
  CONSTANTS,
  noneRichTextNodeLineHeight
} from '../../constants/constant'
import {
  bufferPendingNodeTextEditInput,
  captureInsertedNodeRollbackState,
  resolveCurrentNodeTextEditTarget,
  rollbackRejectedInsertedNode,
  reusePendingNodeTextEditAdmission
} from './node/nodeCooperateState'

const SMM_NODE_EDIT_WRAP = 'smm-node-edit-wrap'

//  节点文字编辑类
export default class TextEdit {
  //  构造函数
  constructor(renderer) {
    this.renderer = renderer
    this.mindMap = renderer.mindMap
    // 当前编辑的节点
    this.currentNode = null
    // 文本编辑框
    this.textEditNode = null
    // 文本编辑框是否显示
    this.showTextEdit = false
    // 如果编辑过程中缩放画布了，那么缓存当前编辑的内容
    this.cacheEditingText = ''
    this.hasBodyMousedown = false
    this.textNodePaddingX = 5
    this.textNodePaddingY = 3
    // beforeTextEdit 可能等待服务端租约。等待期间该临时插入仍未获准落库，
    // 必须能在点击别处、离开页面或实例销毁时同步撤销。
    this.pendingTextEditAdmission = null
    // 概要运行时对象会按数组下标复用，重排时 getData('uid') 可在 render_end
    // 前变成另一条概要。编辑开始时独立冻结持久 UID，后续换绑不能再读旧实例。
    this.currentTextEditNodeUid = ''
    // 连续录入可能跨过 INSERT_* 的 requestAnimationFrame 渲染边界。按新
    // 节点持久 UID 暂存后续分段，待其 node_dblclick 准入时再移交。
    this.deferredPendingTextEditSequence = null
    this.mindMap.addEditNodeClass(SMM_NODE_EDIT_WRAP)
    this.bindEvent()
  }

  //  事件
  bindEvent() {
    this.show = this.show.bind(this)
    this.onScale = this.onScale.bind(this)
    this.onKeydown = this.onKeydown.bind(this)
    // 节点双击事件
    this.mindMap.on(
      'node_dblclick',
      (node, e, isInserting, insertionType) => {
        this.show({ node, e, isInserting, insertionType })
      }
    )
    // 点击事件
    this.mindMap.on('draw_click', () => {
      // 隐藏文本编辑框
      this.hideEditTextBox()
    })
    this.mindMap.on('body_mousedown', () => {
      this.hasBodyMousedown = true
    })
    this.mindMap.on('body_click', () => {
      if (!this.hasBodyMousedown) return
      this.hasBodyMousedown = false
      // 隐藏文本编辑框
      if (this.mindMap.opt.isEndNodeTextEditOnClickOuter) {
        this.hideEditTextBox()
      }
    })
    this.mindMap.on('svg_mousedown', () => {
      // 隐藏文本编辑框
      this.hideEditTextBox()
    })
    // 展开收缩按钮点击事件
    this.mindMap.on('expand_btn_click', () => {
      this.hideEditTextBox()
    })
    // 节点激活前事件
    this.mindMap.on('before_node_active', node => {
      const pendingUid = String(
        this.pendingTextEditAdmission?.nodeUid || ''
      ).trim()
      const editingUid = String(this.currentTextEditNodeUid || '').trim()
      const activeUid = String(node?.getData?.('uid') || node?.uid || '').trim()
      // 完整重绘会用持久化 isActive 激活同 UID 的新运行时实例。此时旧
      // renderer.root 可能已经清空，取消准入既无法补偿删除，还会留下幽灵
      // 默认节点；保留申请并在 render_end/lease grant 后按 UID 换绑。
      if (
        activeUid
        && (pendingUid === activeUid || editingUid === activeUid)
      ) return
      this.hideEditTextBox()
    })
    // 鼠标滚动事件
    this.mindMap.on('mousewheel', () => {
      if (
        this.mindMap.opt.mousewheelAction === CONSTANTS.MOUSE_WHEEL_ACTION.MOVE
      ) {
        this.hideEditTextBox()
      }
    })
    // 注册编辑快捷键
    this.mindMap.keyCommand.addShortcut('F2', () => {
      if (this.renderer.activeNodeList.length <= 0) {
        return
      }
      this.show({
        node: this.renderer.activeNodeList[0]
      })
    })
    this.mindMap.on('scale', this.onScale)
    this.mindMap.on('node_text_edit_end', node => {
      const endedUid = String(node?.getData?.('uid') || node?.uid || '').trim()
      if (
        !this.isShowTextEdit()
        || (endedUid && endedUid === this.currentTextEditNodeUid)
      ) {
        this.currentTextEditNodeUid = ''
      }
    })
    // 始终监听待准入编辑器的降级输入。enableAutoEnterTextEditWhenKeydown
    // 只控制“已有节点按字母进入编辑”，不能让显式 INSERT_* 新建节点在
    // 等待服务端租约时丢字。
    // capture 阶段必须早于 KeyCommand 的 window bubble listener。否则隐藏
    // textarea 被 WebView 拒绝聚焦时，Enter/Tab/Delete 会先执行结构命令，
    // 待准入输入兜底即使随后 stopPropagation 也已经来不及。
    window.addEventListener('keydown', this.onKeydown, true)
    this.mindMap.on('beforeDestroy', () => {
      this.cancelPendingTextEditAdmission()
      this.unBindEvent()
    })
    this.mindMap.on('after_update_config', (opt, lastOpt) => {
      if (
        opt.openRealtimeRenderOnNodeTextEdit !==
        lastOpt.openRealtimeRenderOnNodeTextEdit
      ) {
        if (this.mindMap.richText) {
          this.mindMap.richText.onOpenRealtimeRenderOnNodeTextEditConfigUpdate(
            opt.openRealtimeRenderOnNodeTextEdit
          )
        } else {
          this.onOpenRealtimeRenderOnNodeTextEditConfigUpdate(
            opt.openRealtimeRenderOnNodeTextEdit
          )
        }
      }
    })
    // 本地命令和远端增量都会改变布局；远端 updateData 不会触发
    // afterExecCommand，因此只要编辑器仍显示，每次渲染完成都按当前节点
    // 的新坐标重定位，避免输入框留在旧位置。
    this.mindMap.on('node_tree_render_end', () => {
      // INSERT_* 若被插件拦截或没有生成预期节点，不能让旧输入串到未来
      // 某次偶然复用 UID 的编辑。正常入口会在 render_end 前同步 consume。
      this.scheduleDeferredPendingTextEditSequenceCleanup()
      if (!this.isShowTextEdit()) return
      if (!this.rebindCurrentTextEditNodeAfterRender()) return
      this.updateTextEditNode()
    })
  }

  // 解绑事件
  unBindEvent() {
    window.removeEventListener('keydown', this.onKeydown, true)
  }

  scheduleDeferredPendingTextEditSequenceCleanup() {
    const sequence = this.deferredPendingTextEditSequence
    if (!sequence || this.pendingTextEditAdmission) return
    // 同步渲染会先 emit render_end，再按 post-order 调用新节点 finishRender，
    // 后者才触发 show()/takeDeferred。延后一微任务，给目标节点一次同步
    // 消费机会；仍未消费才说明 INSERT_* 没有生成预期目标。
    queueMicrotask(() => {
      if (
        this.deferredPendingTextEditSequence === sequence
        && !this.pendingTextEditAdmission
      ) this.deferredPendingTextEditSequence = null
    })
  }

  // 按键事件
  onKeydown(e) {
    const activeNodeList = this.mindMap.renderer.activeNodeList
    if (activeNodeList.length <= 0 || activeNodeList.length > 1) return
    const node = activeNodeList[0]
    // 新节点可能仍在等待服务端租约。焦点若因浏览器策略仍停在工具栏或
    // 菜单按钮，也要在 body 限制之前接管输入。真正的输入控件保持原生行为。
    if (
      !this.isEditableTextInputTarget(e.target)
      && this.queuePendingTextEditContinuation(
        this.pendingTextEditAdmission,
        node,
        e
      )
    ) {
      e.preventDefault()
      e.stopImmediatePropagation?.()
      return
    }
    if (
      !this.isEditableTextInputTarget(e.target)
      && bufferPendingNodeTextEditInput(
        this.pendingTextEditAdmission,
        node,
        e
      )
    ) {
      e.preventDefault()
      e.stopImmediatePropagation?.()
      return
    }
    if (!this.mindMap.opt.enableAutoEnterTextEditWhenKeydown) return
    if (e.target !== document.body) return
    // 当正在输入中文或英文或数字时，如果没有按下组合键，那么自动进入文本编辑模式
    if (node && this.checkIsAutoEnterTextEditKey(e)) {
      // 忽略第一个键值，避免中文输入法时进入编辑会导致第一个键值变成字母的问题
      // 带来的问题是按的第一下纯粹是进入文本编辑，但没有变成输入
      e.preventDefault()
      this.show({
        node,
        e,
        isInserting: false,
        isFromKeyDown: true
      })
    }
  }

  isEditableTextInputTarget(target) {
    if (!target || target === document.body) return false
    if (target.isContentEditable) return true
    const tagName = String(target.tagName || '').toUpperCase()
    if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT') {
      return true
    }
    return Boolean(target.closest?.('[contenteditable="true"]'))
  }

  // 判断是否是自动进入文本编模式的按钮
  checkIsAutoEnterTextEditKey(e) {
    const keyCode = e.keyCode
    return (
      (keyCode === 229 ||
        (keyCode >= 65 && keyCode <= 90) ||
        (keyCode >= 48 && keyCode <= 57)) &&
      !this.mindMap.keyCommand.hasCombinationKey(e)
    )
  }

  // 提交当前编辑内容，并以编辑节点作为后续插入命令的明确目标
  finishTextEditAndInsert(command) {
    const currentNode = this.getCurrentEditNode()
    const insertionOwner = command === 'INSERT_NODE'
      ? currentNode?.parent
      : currentNode
    const children = insertionOwner?.nodeData?.children
    const previousChildUids = new Set(
      (Array.isArray(children) ? children : [])
        .map(child => String(child?.data?.uid || '').trim())
        .filter(Boolean)
    )
    this.hideEditTextBox()
    if (currentNode) {
      this.mindMap.execCommand(command, true, [currentNode])
    }
    const insertedNode = (Array.isArray(children) ? children : []).find(child => {
      const uid = String(child?.data?.uid || '').trim()
      return uid && !previousChildUids.has(uid)
    })
    return String(insertedNode?.data?.uid || '').trim()
  }

  //  注册临时快捷键
  registerTmpShortcut() {
    this.mindMap.keyCommand.addShortcut('Enter', () => {
      // 创建节点后会立即进入文字编辑。此时再次按 Enter 应提交当前
      // 文本并继续创建同级节点，才能支持连续快速录入。
      this.finishTextEditAndInsert('INSERT_NODE')
    })
    this.mindMap.keyCommand.addShortcut('Tab', () => {
      // Tab 同样提交当前文本，并以当前节点为父节点连续向下创建。
      this.finishTextEditAndInsert('INSERT_CHILD_NODE')
    })
  }

  // 获取当前文本编辑框是否处于显示状态，也就是是否处在文本编辑状态
  isShowTextEdit() {
    if (this.mindMap.richText) {
      return this.mindMap.richText.showTextEdit
    }
    return this.showTextEdit
  }

  // 设置文本编辑框是否处于显示状态
  setIsShowTextEdit(val) {
    this.showTextEdit = val
    if (val) {
      this.mindMap.keyCommand.stopCheckInSvg()
    } else {
      this.mindMap.keyCommand.recoveryCheckInSvg()
    }
  }

  // Presence 中的选区不会阻止编辑；仅当另一个会话明确声明正在编辑该
  // 节点文本时才拒绝进入。beforeTextEdit 可能异步，因此调用方会在其
  // 前后各检查一次，避免等待期间收到的远端占用被漏掉。
  isTextEditBlockedByRemote(node) {
    if (
      typeof this.mindMap.opt.isNodeTextEditLeaseAuthoritative === 'function'
      && this.mindMap.opt.isNodeTextEditLeaseAuthoritative()
    ) return false
    return Boolean(
      this.mindMap.opt.onlyOneEnableTextEditOnCooperate
      && this.getCurrentEditNode() !== node
      && node?.isTextEditOccupied?.()
    )
  }

  emitTextEditBlocked(node, reason = 'occupied') {
    this.mindMap.emit(
      'node_text_edit_blocked',
      node,
      [...(node?.editingUserList || [])],
      reason
    )
  }

  // 新节点的真实编辑器需要等待服务端租约。同步创建并聚焦一个不可见的
  // textarea，让浏览器原生处理选区、退格、粘贴和 IME composition；获锁
  // 后再把最终值一次性移交给普通或 Quill 编辑器。
  createPendingTextEditInput(admission, node, isInserting) {
    if (!admission || !isInserting || typeof document === 'undefined') return
    const input = document.createElement('textarea')
    const rawText = String(node?.getData?.('text') || '')
    let initialText = rawText
    if (node?.getData?.('richText')) {
      try {
        initialText = getTextFromHtml(rawText)
      } catch {
        initialText = rawText
      }
    }
    input.value = initialText
    admission.pendingInputText = initialText
    admission.pendingInputTouched = false
    admission.pendingInputSegments = [{
      text: initialText,
      touched: false,
      continuationCommand: ''
    }]
    admission.pendingInputSegmentIndex = 0
    input.classList.add(SMM_NODE_EDIT_WRAP, 'smm-node-edit-admission-buffer')
    input.setAttribute('aria-label', '正在准备节点文本编辑')
    input.style.cssText = `
      position: fixed;
      left: -10000px;
      top: 0;
      width: 1px;
      height: 1px;
      padding: 0;
      border: 0;
      opacity: 0;
      pointer-events: none;
    `
    const syncValue = () => {
      if (this.pendingTextEditAdmission !== admission) return
      admission.pendingInputText = input.value
      admission.pendingInputTouched = true
      const segment = admission.pendingInputSegments?.[
        admission.pendingInputSegmentIndex
      ]
      if (segment) {
        segment.text = input.value
        segment.touched = true
      }
    }
    input.addEventListener('input', syncValue)
    input.addEventListener('compositionstart', () => {
      if (this.pendingTextEditAdmission === admission) {
        admission.pendingCompositionActive = true
      }
    })
    input.addEventListener('compositionend', () => {
      syncValue()
      admission.pendingCompositionActive = false
      const resolve = admission.resolvePendingComposition
      admission.resolvePendingComposition = null
      resolve?.(true)
    })
    input.addEventListener('keydown', event => {
      // 防止节点/外框的全局 Delete、Enter、Tab 快捷键先于租约结果执行。
      event.stopPropagation()
      if (
        !event.isComposing
        && event.keyCode !== 229
        && (event.key === 'Enter' || event.key === 'Tab')
      ) {
        event.preventDefault()
        this.queuePendingTextEditContinuation(admission, node, event)
        return
      }
      if (
        (event.key === 'Backspace' || event.key === 'Delete')
        && input.value === ''
      ) {
        syncValue()
      }
    })
    input.addEventListener('keyup', event => event.stopPropagation())
    const targetNode = this.mindMap.opt.customInnerElsAppendTo || document.body
    targetNode.appendChild(input)
    admission.pendingInputElement = input
    try {
      input.focus({ preventScroll: true })
      input.select()
    } catch {
      // 某些嵌入式 WebView 会拒绝脚本聚焦；window keydown 缓存继续兜底。
    }
  }

  removePendingTextEditInput(admission) {
    const input = admission?.pendingInputElement
    if (input) {
      input.parentNode?.removeChild(input)
      admission.pendingInputElement = null
    }
    admission.pendingCompositionActive = false
    const resolve = admission.resolvePendingComposition
    admission.resolvePendingComposition = null
    resolve?.(false)
  }

  queuePendingTextEditContinuation(admission, node, event) {
    if (
      !admission
      || event?.isComposing
      || event?.keyCode === 229
      || (event?.key !== 'Enter' && event?.key !== 'Tab')
    ) return false
    const pendingUid = String(admission.nodeUid || '').trim()
    const nodeUid = String(node?.getData?.('uid') || node?.uid || '').trim()
    if (!pendingUid || pendingUid !== nodeUid) return false
    const segments = Array.isArray(admission.pendingInputSegments)
      ? admission.pendingInputSegments
      : [{
          text: admission.pendingInputText || '',
          touched: admission.pendingInputTouched === true,
          continuationCommand: ''
        }]
    const currentIndex = Math.max(0, segments.length - 1)
    const current = segments[currentIndex]
    const input = admission.pendingInputElement
    // textarea 获得焦点时浏览器原生值是权威输入；聚焦被拒绝时则由 window
    // fallback 直接写 admission。不能再用从未接收按键的 textarea 空值覆盖。
    if (
      input
      && (
        event?.target === input
        || input.ownerDocument?.activeElement === input
      )
    ) current.text = input.value
    current.continuationCommand = event.key === 'Enter'
      ? 'INSERT_NODE'
      : 'INSERT_CHILD_NODE'
    segments.push({ text: '', touched: false, continuationCommand: '' })
    admission.pendingInputSegments = segments
    admission.pendingInputSegmentIndex = segments.length - 1
    admission.pendingInputText = ''
    admission.pendingInputTouched = false
    if (input) {
      input.value = ''
      input.setSelectionRange?.(0, 0)
    }
    return true
  }

  installPendingTextEditSegments(admission, segments) {
    if (!admission || !Array.isArray(segments) || segments.length === 0) return
    admission.pendingInputSegments = segments.map(segment => ({
      text: String(segment?.text || ''),
      touched: segment?.touched === true,
      continuationCommand: segment?.continuationCommand || ''
    }))
    const inputSegmentIndex = admission.pendingInputSegments.length - 1
    admission.pendingInputSegmentIndex = inputSegmentIndex
    const inputSegment = admission.pendingInputSegments[inputSegmentIndex]
    admission.pendingInputText = inputSegment.text
    admission.pendingInputTouched = inputSegment.touched
    const input = admission.pendingInputElement
    if (input) {
      input.value = inputSegment.text
      input.setSelectionRange?.(inputSegment.text.length, inputSegment.text.length)
    }
  }

  waitForPendingTextEditComposition(admission) {
    if (!admission?.pendingCompositionActive) return Promise.resolve(true)
    return new Promise(resolve => {
      admission.resolvePendingComposition = resolve
    })
  }

  takeDeferredPendingTextEditSegments(node, isInserting) {
    if (!isInserting || !this.deferredPendingTextEditSequence) return []
    const nodeUid = String(node?.getData?.('uid') || node?.uid || '').trim()
    if (nodeUid !== this.deferredPendingTextEditSequence.nodeUid) return []
    const segments = this.deferredPendingTextEditSequence.segments
    this.deferredPendingTextEditSequence = null
    return Array.isArray(segments) ? segments : []
  }

  continuePendingTextEditSequence(nodeUid, command, remainingSegments) {
    const currentNode = this.getCurrentEditNode()
    const currentUid = currentNode?.getData?.('uid') || currentNode?.uid || ''
    if (!currentNode || currentUid !== nodeUid) return false
    const insertedNodeUid = this.finishTextEditAndInsert(command)
    if (!Array.isArray(remainingSegments) || remainingSegments.length === 0) {
      return true
    }
    if (!insertedNodeUid) return false
    // INSERT_* 只在下一帧创建运行时节点，不能假设 execCommand 返回前已经
    // 有 nextAdmission。用刚写入 renderTree 的持久 UID 跨 RAF 精确移交。
    this.deferredPendingTextEditSequence = {
      nodeUid: insertedNodeUid,
      segments: remainingSegments.map(segment => ({ ...segment }))
    }
    return true
  }

  // updateData 可重建概要运行时节点（同一 owner 的概要数量变化尤其常见）。
  // DOM 编辑内容仍有效时按持久 UID 换绑当前实例，避免最终提交写回脱离树的旧对象。
  rebindCurrentTextEditNodeAfterRender() {
    const currentNode = this.getCurrentEditNode()
    if (!currentNode) return false
    const nodeUid = this.currentTextEditNodeUid
    const currentRuntimeNode = nodeUid
      ? this.renderer.findNodeByUid?.(nodeUid)
      : null
    if (!currentRuntimeNode) return false
    if (this.mindMap.richText) {
      this.mindMap.richText.node = currentRuntimeNode
    } else {
      this.currentNode = currentRuntimeNode
    }
    return true
  }

  rollbackRejectedInsertion(rollbackState) {
    try {
      return rollbackRejectedInsertedNode(
        rollbackState,
        this.renderer,
        this.mindMap
      )
    } catch (error) {
      this.mindMap.opt.errorHandler(ERROR_TYPES.BEFORE_TEXT_EDIT_ERROR, error)
      return false
    }
  }

  cancelPendingTextEditAdmission() {
    const admission = this.pendingTextEditAdmission
    if (!admission) return false
    // 先让补偿删除进入历史/Yjs，再取消或释放服务端申请；否则另一浏览器
    // 可能先获锁并从仍含默认节点的状态继续编辑。
    this.pendingTextEditAdmission = null
    this.removePendingTextEditInput(admission)
    const rolledBack = this.rollbackRejectedInsertion(admission.rollbackState)
    this.mindMap.opt.releaseNodeTextEditLease?.(admission.nodeUid)
    return rolledBack
  }

  // 显示文本编辑框
  // isInserting：是否是刚创建的节点
  // isFromKeyDown：是否是在按键事件进入的编辑
  async show({
    node,
    e,
    isInserting = false,
    insertionType = 'node',
    isFromKeyDown = false,
    isFromScale = false
  }) {
    // 键盘、双击等入口可能在同一节点仍等待服务端租约时再次触发。
    // 这不是切换目标：复用原准入并缓存期间的可打印输入，避免误回滚
    // INSERT_NODE/INSERT_CHILD_NODE 刚创建的节点。
    if (reusePendingNodeTextEditAdmission(
      this.pendingTextEditAdmission,
      node,
      e
    )) return
    const inheritedPendingSegments = this.takeDeferredPendingTextEditSegments(
      node,
      isInserting
    )
    // 真正切换目标时才撤销旧入口，防止两个迟到结果争用同一编辑框。
    this.cancelPendingTextEditAdmission()
    // 使用了自定义节点内容那么不响应编辑事件
    if (node.isUseCustomNodeContent()) {
      return
    }
    const insertionRollbackState = captureInsertedNodeRollbackState(node, {
      isInserting,
      insertionType
    })
    if (this.isTextEditBlockedByRemote(node)) {
      this.emitTextEditBlocked(node)
      this.rollbackRejectedInsertion(insertionRollbackState)
      return
    }
    // 如果有正在编辑中的节点，那么先结束它
    const currentEditNode = this.getCurrentEditNode()
    if (currentEditNode) {
      this.hideEditTextBox()
    }
    const { beforeTextEdit, openRealtimeRenderOnNodeTextEdit } =
      this.mindMap.opt
    let pendingInputText = ''
    let pendingInputTouched = false
    let pendingContinuationCommand = ''
    let pendingRemainingSegments = []
    if (inheritedPendingSegments.length > 0) {
      const first = inheritedPendingSegments[0]
      pendingInputText = String(first?.text || '')
      pendingInputTouched = first?.touched === true
      pendingContinuationCommand = first?.continuationCommand || ''
      pendingRemainingSegments = inheritedPendingSegments.slice(1)
    }
    if (typeof beforeTextEdit === 'function') {
      const admission = {
        nodeUid: node?.getData?.('uid') || node?.uid || '',
        rollbackState: insertionRollbackState,
        pendingInputText: '',
        pendingInputTouched: false,
        pendingInputSegments: null,
        pendingInputSegmentIndex: 0,
        pendingCompositionActive: false,
        resolvePendingComposition: null
      }
      this.pendingTextEditAdmission = admission
      this.createPendingTextEditInput(admission, node, isInserting)
      if (inheritedPendingSegments.length > 0) {
        this.installPendingTextEditSegments(admission, inheritedPendingSegments)
      }
      let isShow = false
      try {
        isShow = await beforeTextEdit(node, isInserting)
      } catch (error) {
        isShow = false
        this.mindMap.opt.errorHandler(ERROR_TYPES.BEFORE_TEXT_EDIT_ERROR, error)
      }
      // 服务端 grant 可能先于中文候选提交。保留临时输入焦点直到
      // compositionend，避免强制换焦点把候选词变成拼音或直接丢弃。
      if (
        isShow
        && this.pendingTextEditAdmission === admission
        && !await this.waitForPendingTextEditComposition(admission)
      ) return
      // 点击别处、终止页面或新 show() 已取消本次准入。旧 Promise 即使
      // 最终返回 true 也绝不能重新打开编辑器。
      if (this.pendingTextEditAdmission !== admission) return
      this.removePendingTextEditInput(admission)
      this.pendingTextEditAdmission = null
      const segments = Array.isArray(admission.pendingInputSegments)
        && admission.pendingInputSegments.length > 0
        ? admission.pendingInputSegments
        : [{
            text: admission.pendingInputText,
            touched: admission.pendingInputTouched,
            continuationCommand: ''
          }]
      pendingInputText = String(segments[0]?.text || '')
      pendingInputTouched = segments[0]?.touched === true
      pendingContinuationCommand = segments[0]?.continuationCommand || ''
      pendingRemainingSegments = segments.slice(1)
      if (!isShow) {
        if (this.mindMap.opt.isNodeTextEditLeaseAuthoritative?.() === true) {
          this.emitTextEditBlocked(
            node,
            this.mindMap.opt.getNodeTextEditLeaseFailureReason?.()
              || 'unavailable'
          )
        }
        this.rollbackRejectedInsertion(insertionRollbackState)
        return
      }
    }
    let leasedNodeUid = ''
    let opened = false
    try {
      const authoritativeNodeEditLease = (
        typeof this.mindMap.opt.isNodeTextEditLeaseAuthoritative === 'function'
        && this.mindMap.opt.isNodeTextEditLeaseAuthoritative()
      )
      if (authoritativeNodeEditLease) {
        leasedNodeUid = node?.getData?.('uid') || node?.uid || ''
        const currentNode = resolveCurrentNodeTextEditTarget(node, this.renderer, {
          authoritative: true,
          readonly: this.mindMap.opt.readonly,
        })
        // 租约等待期间远端可能删除节点或整树重建。只允许当前 renderer 中
        // 仍有效的 UID 实例继续，未真正打开编辑器的任何退出路径都在 finally 归还租约。
        if (!currentNode) return
        node = currentNode
      }
      if (this.isTextEditBlockedByRemote(node)) {
        this.emitTextEditBlocked(node)
        return
      }
      const { offsetLeft, offsetTop } = checkNodeOuter(this.mindMap, node)
      this.mindMap.view.translateXY(offsetLeft, offsetTop)
      const g = node._textData.node
      // 需要先显示，不然宽高获取到的可能是0
      if (openRealtimeRenderOnNodeTextEdit) {
        g.show()
      }
      const rect = g.node.getBoundingClientRect()
      // 如果开启了大小实时更新，那么直接隐藏节点原文本
      if (openRealtimeRenderOnNodeTextEdit) {
        g.hide()
      }
      const params = {
        node,
        rect,
        isInserting,
        isFromKeyDown,
        isFromScale
      }
      this.currentTextEditNodeUid = String(
        node?.getData?.('uid') || node?.uid || ''
      ).trim()
      if (this.mindMap.richText) {
        this.mindMap.richText.showEditText(params)
      } else {
        this.currentNode = node
        this.showEditTextBox(params)
      }
      opened = (
        this.isShowTextEdit()
        && this.getCurrentEditNode() === node
      )
      if (opened && pendingInputTouched) {
        this.applyPendingTextEditInput(pendingInputText, {
          replaceCurrentText: Boolean(
            isInserting
            || (
              this.mindMap.opt.selectTextOnEnterEditText
              && !isFromKeyDown
            )
          )
        })
      }
      if (opened && pendingContinuationCommand) {
        const openedNodeUid = node?.getData?.('uid') || node?.uid || ''
        queueMicrotask(() => {
          const current = this.getCurrentEditNode()
          const currentUid = current?.getData?.('uid') || current?.uid || ''
          if (currentUid === openedNodeUid) {
            this.continuePendingTextEditSequence(
              openedNodeUid,
              pendingContinuationCommand,
              pendingRemainingSegments
            )
          }
        })
      }
    } catch (error) {
      // show() 被事件直接调用，因此内部吸收 DOM/渲染异常，避免产生
      // unhandled rejection；同时仍通过统一 errorHandler 暴露错误。
      opened = (
        this.isShowTextEdit()
        && this.getCurrentEditNode() === node
      )
      this.mindMap.opt.errorHandler(ERROR_TYPES.BEFORE_TEXT_EDIT_ERROR, error)
    } finally {
      if (leasedNodeUid && !opened) {
        this.mindMap.opt.releaseNodeTextEditLease?.(leasedNodeUid)
      }
      if (!opened) {
        this.currentTextEditNodeUid = ''
        this.rollbackRejectedInsertion(insertionRollbackState)
      }
    }
  }

  // 把租约等待期间由 body keydown 拦截的输入恢复到刚打开的编辑器。
  // 新建节点/全选进入时替换默认文字；普通节点则按当前光标或选区插入。
  applyPendingTextEditInput(text, { replaceCurrentText = false } = {}) {
    if (typeof text !== 'string' || (!text && !replaceCurrentText)) return false
    const richText = this.mindMap.richText
    const quill = richText?.showTextEdit ? richText.quill : null
    if (quill) {
      if (replaceCurrentText) {
        quill.setText(text)
        quill.setSelection(text.length, 0)
        return true
      }
      const range = quill.getSelection?.() || {
        index: Math.max(0, (quill.getLength?.() || 1) - 1),
        length: 0
      }
      if (range.length > 0) quill.deleteText(range.index, range.length)
      quill.insertText(range.index, text)
      quill.setSelection(range.index + text.length, 0)
      return true
    }
    if (!this.showTextEdit || !this.textEditNode) return false
    if (replaceCurrentText) {
      this.textEditNode.textContent = text
      focusInput(this.textEditNode)
      this.emitTextChangeEvent()
      return true
    }
    const selection = window.getSelection?.()
    let range = null
    if (selection?.rangeCount) {
      const candidate = selection.getRangeAt(0)
      const container = candidate.commonAncestorContainer
      if (
        container === this.textEditNode
        || this.textEditNode.contains(container)
      ) range = candidate
    }
    if (!range) {
      range = document.createRange()
      range.selectNodeContents(this.textEditNode)
      range.collapse(false)
    }
    range.deleteContents()
    const inputNode = document.createTextNode(text)
    range.insertNode(inputNode)
    range.setStartAfter(inputNode)
    range.collapse(true)
    selection?.removeAllRanges?.()
    selection?.addRange?.(range)
    this.emitTextChangeEvent()
    return true
  }

  // 当openRealtimeRenderOnNodeTextEdit配置更新后需要更新编辑框样式
  onOpenRealtimeRenderOnNodeTextEditConfigUpdate(
    openRealtimeRenderOnNodeTextEdit
  ) {
    if (!this.textEditNode) return
    this.textEditNode.style.background = openRealtimeRenderOnNodeTextEdit
      ? 'transparent'
      : this.currentNode
      ? this.getBackground(this.currentNode)
      : ''
    this.textEditNode.style.boxShadow = openRealtimeRenderOnNodeTextEdit
      ? 'none'
      : '0 0 20px rgba(0,0,0,.5)'
  }

  // 处理画布缩放
  onScale() {
    const node = this.getCurrentEditNode()
    if (!node) return
    // 缩放只改变浮层几何，不应关闭编辑器并重新申请服务端租约。保持同一
    // DOM/Quill 实例也能保留光标、IME 候选与尚未提交的最后字符。
    this.updateTextEditNode()
  }

  //  显示文本编辑框
  showEditTextBox({ node, rect, isInserting, isFromKeyDown, isFromScale }) {
    if (this.showTextEdit) return
    const {
      nodeTextEditZIndex,
      textAutoWrapWidth,
      selectTextOnEnterEditText,
      openRealtimeRenderOnNodeTextEdit,
      autoEmptyTextWhenKeydownEnterEdit
    } = this.mindMap.opt
    if (!isFromScale) {
      this.mindMap.emit('before_show_text_edit')
    }
    this.registerTmpShortcut()
    if (!this.textEditNode) {
      this.textEditNode = document.createElement('div')
      this.textEditNode.classList.add(SMM_NODE_EDIT_WRAP)
      this.textEditNode.style.cssText = `
        position: fixed;
        box-sizing: border-box;
        ${
          openRealtimeRenderOnNodeTextEdit
            ? ''
            : `box-shadow: 0 0 20px rgba(0,0,0,.5);`
        }
        padding: ${this.textNodePaddingY}px ${this.textNodePaddingX}px;
        margin-left: -${this.textNodePaddingX}px;
        margin-top: -${this.textNodePaddingY}px;
        outline: none; 
        word-break: break-all;
        line-break: anywhere;
      `
      this.textEditNode.setAttribute('contenteditable', true)
      this.textEditNode.addEventListener('keyup', e => {
        e.stopPropagation()
      })
      this.textEditNode.addEventListener('click', e => {
        e.stopPropagation()
      })
      this.textEditNode.addEventListener('mousedown', e => {
        e.stopPropagation()
      })
      this.textEditNode.addEventListener('keydown', e => {
        if (this.checkIsAutoEnterTextEditKey(e)) {
          e.stopPropagation()
        }
      })
      this.textEditNode.addEventListener('paste', e => {
        const text = e.clipboardData.getData('text')
        const { isSmm, data } = checkSmmFormatData(text)
        if (isSmm && data[0] && data[0].data) {
          // 只取第一个节点的纯文本
          handleInputPasteText(e, getTextFromHtml(data[0].data.text))
        } else {
          handleInputPasteText(e)
        }
        this.emitTextChangeEvent()
      })
      this.textEditNode.addEventListener('input', () => {
        this.emitTextChangeEvent()
      })
      const targetNode =
        this.mindMap.opt.customInnerElsAppendTo || document.body
      targetNode.appendChild(this.textEditNode)
    }
    const scale = this.mindMap.view.scale
    const fontSize = node.style.merge('fontSize')
    const textLines = (this.cacheEditingText || node.getData('text'))
      .split(/\n/gim)
      .map(item => {
        return htmlEscape(item)
      })
    const isMultiLine = node._textData.node.attr('data-ismultiLine') === 'true'
    node.style.domText(this.textEditNode, scale)
    if (!openRealtimeRenderOnNodeTextEdit) {
      this.textEditNode.style.background = this.getBackground(node)
    }
    this.textEditNode.style.zIndex = nodeTextEditZIndex
    if (isFromKeyDown && autoEmptyTextWhenKeydownEnterEdit) {
      this.textEditNode.innerHTML = ''
    } else {
      this.textEditNode.innerHTML = textLines.join('<br>')
    }
    this.textEditNode.style.minWidth =
      rect.width + this.textNodePaddingX * 2 + 'px'
    this.textEditNode.style.minHeight = rect.height + 'px'
    this.textEditNode.style.left = Math.floor(rect.left) + 'px'
    this.textEditNode.style.top = Math.floor(rect.top) + 'px'
    this.textEditNode.style.display = 'block'
    this.textEditNode.style.maxWidth = textAutoWrapWidth * scale + 'px'
    if (isMultiLine) {
      this.textEditNode.style.lineHeight = noneRichTextNodeLineHeight
      this.textEditNode.style.transform = `translateY(${
        (((noneRichTextNodeLineHeight - 1) * fontSize) / 2) * scale
      }px)`
    } else {
      this.textEditNode.style.lineHeight = 'normal'
    }
    this.setIsShowTextEdit(true)
    this.mindMap.emit('node_text_edit_start', node)
    // 选中文本
    // if (!this.cacheEditingText) {
    //   selectAllInput(this.textEditNode)
    // }
    if (isInserting || (selectTextOnEnterEditText && !isFromKeyDown)) {
      selectAllInput(this.textEditNode)
    } else {
      focusInput(this.textEditNode)
    }
    this.cacheEditingText = ''
  }

  // 派发节点文本编辑事件
  emitTextChangeEvent() {
    this.mindMap.emit('node_text_edit_change', {
      node: this.currentNode,
      text: this.getEditText(),
      richText: false
    })
  }

  // 更新文本编辑框的大小和位置
  updateTextEditNode() {
    if (this.mindMap.richText) {
      this.mindMap.richText.updateTextEditNode()
      return
    }
    if (!this.showTextEdit || !this.currentNode) {
      return
    }
    const rect = this.currentNode._textData.node.node.getBoundingClientRect()
    const scale = this.mindMap.view.scale
    const fontSize = this.currentNode.style.merge('fontSize')
    const isMultiLine = (
      this.currentNode._textData.node.attr('data-ismultiLine') === 'true'
    )
    this.currentNode.style.domText(this.textEditNode, scale)
    this.textEditNode.style.minWidth =
      rect.width + this.textNodePaddingX * 2 + 'px'
    this.textEditNode.style.minHeight =
      rect.height + this.textNodePaddingY * 2 + 'px'
    this.textEditNode.style.left = Math.floor(rect.left) + 'px'
    this.textEditNode.style.top = Math.floor(rect.top) + 'px'
    this.textEditNode.style.maxWidth =
      this.mindMap.opt.textAutoWrapWidth * scale + 'px'
    this.textEditNode.style.lineHeight = isMultiLine
      ? noneRichTextNodeLineHeight
      : 'normal'
    this.textEditNode.style.transform = isMultiLine
      ? `translateY(${(
          ((noneRichTextNodeLineHeight - 1) * fontSize) / 2
        ) * scale}px)`
      : 'translateY(0)'
  }

  // 获取编辑区域的背景填充
  getBackground(node) {
    const gradientStyle = node.style.merge('gradientStyle')
    // 当前使用的是渐变色背景
    if (gradientStyle) {
      const startColor = node.style.merge('startColor')
      const endColor = node.style.merge('endColor')
      return `linear-gradient(to right, ${startColor}, ${endColor})`
    } else {
      // 单色背景
      const bgColor = node.style.merge('fillColor')
      const color = node.style.merge('color')
      // 默认使用节点的填充色，否则如果节点颜色是白色的话编辑时看不见
      return bgColor === 'transparent'
        ? isWhite(color)
          ? getVisibleColorFromTheme(this.mindMap.themeConfig)
          : '#fff'
        : bgColor
    }
  }

  // 删除文本编辑元素
  removeTextEditEl() {
    if (this.mindMap.richText) {
      this.mindMap.richText.removeTextEditEl()
      return
    }
    if (!this.textEditNode) return
    const targetNode = this.mindMap.opt.customInnerElsAppendTo || document.body
    targetNode.removeChild(this.textEditNode)
  }

  // 获取当前正在编辑的内容
  getEditText() {
    return getStrWithBrFromHtml(this.textEditNode.innerHTML)
  }

  //  隐藏文本编辑框
  hideEditTextBox() {
    this.cancelPendingTextEditAdmission()
    if (this.mindMap.richText) {
      const result = this.mindMap.richText.hideEditText()
      if (!this.mindMap.richText.showTextEdit) this.currentTextEditNodeUid = ''
      return result
    }
    if (!this.showTextEdit) {
      return
    }
    const currentNode = this.currentNode
    const text = this.getEditText()
    this.currentNode = null
    this.currentTextEditNodeUid = ''
    this.textEditNode.style.display = 'none'
    this.textEditNode.innerHTML = ''
    this.textEditNode.style.fontFamily = 'inherit'
    this.textEditNode.style.fontSize = 'inherit'
    this.textEditNode.style.fontWeight = 'normal'
    this.textEditNode.style.transform = 'translateY(0)'
    this.setIsShowTextEdit(false)
    try {
      this.mindMap.execCommand('SET_NODE_TEXT', currentNode, text)
      // SET_NODE_TEXT 只同步修改运行时模型，data_change_detail 默认仍在
      // Command 的节流队列中。释放服务端租约前必须同步冲刷，使最终文本
      // 已经进入 Yjs/WebSocket 的有序发送队列。
      this.mindMap.command?.flushPendingHistory?.()
      // if (currentNode.isGeneralization) {
      //   // 概要节点
      //   currentNode.generalizationBelongNode.updateGeneralization()
      // }
      this.mindMap.render()
    } finally {
      // 正常路径必须先提交/Yjs 同步再释放；命令或渲染异常时也不能
      // 把服务端租约留到 TTL 才恢复。
      this.mindMap.emit('node_text_edit_end', currentNode)
    }
    this.mindMap.emit(
      'hide_text_edit',
      this.textEditNode,
      this.renderer.activeNodeList,
      currentNode
    )
  }

  // 获取当前正在编辑中的节点实例
  getCurrentEditNode() {
    if (this.mindMap.richText) {
      return this.mindMap.richText.node
    }
    return this.currentNode
  }
}
