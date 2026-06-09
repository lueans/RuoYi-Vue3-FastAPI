/**
 * Yjs 脑图同步管理器
 *
 * 数据模型（细粒度，非整体替换）：
 *   Y.Doc
 *   ├── Y.Map('meta')    → { layout: string, theme: Y.Map, viewData: Y.Map }
 *   └── Y.Map('nodes')   → { [uid]: Y.Map({ data: Y.Map, children: Y.Array<string>, parentUid: string }) }
 *
 * 桥接 simple-mind-map 的 data_change_detail 事件和 Yjs 操作。
 */
import * as Y from 'yjs'
import { ref } from 'vue'
import { MindmapWsClient } from '@/utils/ws-client'

/**
 * 将 simple-mind-map 的节点树扁平化为 uid → node 映射
 */
function flattenTree(node, parentUid, result) {
  if (!node) return
  const uid = node.data?.uid
  if (!uid) return

  result[uid] = {
    data: { ...node.data },
    children: (node.children || []).map(c => c.data?.uid).filter(Boolean),
    parentUid: parentUid || '',
  }

  for (const child of (node.children || [])) {
    flattenTree(child, uid, result)
  }
}

/**
 * 分块 base64 编码，避免大数组调用栈溢出
 */
function uint8ArrayToBase64(bytes) {
  let binary = ''
  const chunkSize = 8192
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length))
    binary += String.fromCharCode.apply(null, chunk)
  }
  return btoa(binary)
}

/**
 * base64 解码为 Uint8Array
 */
function base64ToUint8Array(base64Str) {
  const binary = atob(base64Str)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

export class YjsMindmapSync {
  constructor(mindmapId, mindMapInstance) {
    this.mindmapId = mindmapId
    this.mindMap = mindMapInstance
    this.doc = new Y.Doc()
    this.collaborators = ref([])
    this.isSynced = ref(false)
    this._applyingRemote = false
    this._paused = false
    this._receivedServerState = false
    this._localYjsChange = false

    this.yMeta = this.doc.getMap('meta')
    this.yNodes = this.doc.getMap('nodes')

    this.wsClient = new MindmapWsClient(mindmapId, {
      onAuthenticated: () => { this.isSynced.value = true },
      onClose: () => { this.isSynced.value = false },
      sync_init: (data) => this._handleSyncInit(data),
      update: (data) => this._handleUpdate(data),
      user_joined: (data) => this._handleUserJoined(data),
      user_left: (data) => this._handleUserLeft(data),
      room_users: (data) => this._handleRoomUsers(data),
    })
  }

  start() {
    // 监听 Yjs 文档变更 → 转发到 WebSocket
    this.doc.on('update', (update, origin) => {
      if (origin !== 'remote' && !this._paused) {
        this.wsClient.send({
          type: 'update',
          update: this._encodeUpdate(update),
          state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
        })
      }
    })

    // 监听节点变更 → 同步到脑图实例
    // 仅在远程变更时触发 _applyYjsToMindmap
    // 本地编辑写入 Yjs 时也会触发 observeDeep，需要跳过（_localYjsChange 标志）
    this.yNodes.observeDeep(() => {
      if (!this._applyingRemote && !this._paused && !this._localYjsChange && this.mindMap) {
        this._applyYjsToMindmap()
      }
    })

    this.wsClient.connect()
  }

  destroy() {
    this.wsClient.disconnect()
    this.doc.destroy()
  }

  /** 检查当前是否正在应用远程变更 */
  isApplyingRemote() {
    return this._applyingRemote
  }

  /** 检查同步是否已暂停（版本预览时使用） */
  isPaused() {
    return this._paused
  }

  /** 暂停同步（版本预览时使用） */
  pause() {
    this._paused = true
  }

  /** 恢复同步 */
  resume() {
    this._paused = false
  }

  /** 检查 Yjs 文档是否已有数据 */
  hasData() {
    return this.yNodes.size > 0
  }

  /** 检查是否已收到服务端的 sync_init 状态 */
  hasReceivedServerState() {
    return this._receivedServerState
  }

  /** 将当前脑图数据写入 Yjs（初始化时调用） */
  initFromMindmap(nodeTree) {
    const flat = {}
    flattenTree(nodeTree, null, flat)

    // 使用 'init' origin，doc.on('update') 中可据此区分初始化和增量编辑
    this.doc.transact(() => {
      for (const [uid, nodeInfo] of Object.entries(flat)) {
        const yNode = new Y.Map()
        const yData = new Y.Map()
        for (const [k, v] of Object.entries(nodeInfo.data || {})) {
          yData.set(k, v)
        }
        yNode.set('data', yData)
        yNode.set('children', Y.Array.from(nodeInfo.children || []))
        yNode.set('parentUid', nodeInfo.parentUid)
        this.yNodes.set(uid, yNode)
      }
    }, 'init')
  }

  /** 监听 simple-mind-map 的 data_change_detail 事件，翻译为 Yjs 操作 */
  onDataChangeDetail(detailList) {
    if (!detailList || !detailList.length) return
    if (this._paused) return

    this._localYjsChange = true
    try {
    this.doc.transact(() => {
      for (const detail of detailList) {
        const uid = detail.data?.data?.uid || detail.oldData?.uid
        if (!uid) continue

        switch (detail.action) {
          case 'create': {
            const nodeData = detail.data?.data || {}
            const yNode = new Y.Map()
            const yData = new Y.Map()
            for (const [k, v] of Object.entries(nodeData)) {
              yData.set(k, v)
            }
            yNode.set('data', yData)
            yNode.set('children', Y.Array.from(
              (detail.data.children || []).map(c => c.data?.uid).filter(Boolean)
            ))

            // 查找父节点：遍历现有节点，找到 children 中包含此 uid 的节点
            let parentUid = ''
            this.yNodes.forEach((existingYNode, existingUid) => {
              if (existingUid === uid) return
              const existingChildren = existingYNode.get('children')
              if (existingChildren && existingChildren.toArray().includes(uid)) {
                parentUid = existingUid
              }
            })
            yNode.set('parentUid', parentUid)
            this.yNodes.set(uid, yNode)
            break
          }

          case 'update': {
            const yNode = this.yNodes.get(uid)
            if (yNode) {
              const yData = yNode.get('data')
              if (yData && detail.data?.data) {
                for (const [k, v] of Object.entries(detail.data.data)) {
                  yData.set(k, v)
                }
              }
              // 同步 children 变更（节点被移动时 children 会变化）
              if (detail.data?.children) {
                const yChildren = yNode.get('children')
                if (yChildren) {
                  const newChildUids = (detail.data.children || [])
                    .map(c => c.data?.uid).filter(Boolean)
                  // 简单替换策略
                  yChildren.delete(0, yChildren.length)
                  yChildren.push(newChildUids)
                }
              }
            }
            break
          }

          case 'delete': {
            // 从父节点的 children 中移除
            const deletedUid = detail.oldData?.uid || uid
            if (deletedUid) {
              const deletedYNode = this.yNodes.get(deletedUid)
              if (deletedYNode) {
                const pUid = deletedYNode.get('parentUid')
                if (pUid) {
                  const parentYNode = this.yNodes.get(pUid)
                  if (parentYNode) {
                    const parentChildren = parentYNode.get('children')
                    if (parentChildren) {
                      const idx = parentChildren.toArray().indexOf(deletedUid)
                      if (idx >= 0) {
                        parentChildren.delete(idx, 1)
                      }
                    }
                  }
                }
              }
              this.yNodes.delete(deletedUid)
            }
            break
          }
        }
      }
    })
    } finally {
      this._localYjsChange = false
    }
  }

  /** 从 Yjs 扁平节点重建 simple-mind-map 树形结构 */
  _rebuildTreeFromYjs() {
    const nodes = {}
    this.yNodes.forEach((yNode, uid) => {
      const yData = yNode.get('data')
      nodes[uid] = {
        data: yData ? Object.fromEntries(yData.entries()) : {},
        children: [],
        _parentUid: yNode.get('parentUid') || '',
        _childUids: yNode.get('children')?.toArray() || [],
      }
    })

    const rootUid = Object.keys(nodes).find(id => !nodes[id]._parentUid)
    if (!rootUid || !nodes[rootUid]) return null

    const buildTree = (uid) => {
      const node = nodes[uid]
      if (!node) return null
      return {
        data: node.data,
        children: node._childUids.map(buildTree).filter(Boolean),
      }
    }

    return buildTree(rootUid)
  }

  _applyYjsToMindmap() {
    if (!this.mindMap) return
    this._applyingRemote = true
    try {
      const tree = this._rebuildTreeFromYjs()
      if (tree) {
        // 使用 updateData 而非 setData，保留节点缓存、执行 diff-based render
        this.mindMap.updateData(tree)
        // 清除撤销历史，防止远程变更被 Ctrl+Z 撤销
        // updateData 会 addHistory，但协作者的编辑不应该出现在本地撤销栈中
        this.mindMap.command?.clearHistory?.()
      }
    } finally {
      // 延迟清除标志，确保 updateData 触发的 data_change 事件在标志仍为 true 时传播
      setTimeout(() => { this._applyingRemote = false }, 0)
    }
  }

  _handleSyncInit(data) {
    const state = this._decodeUpdate(data.state)
    Y.applyUpdate(this.doc, state, 'remote')
    this._receivedServerState = true
  }

  _handleUpdate(data) {
    const update = this._decodeUpdate(data.update)
    Y.applyUpdate(this.doc, update, 'remote')
  }

  _handleUserJoined(data) {
    this.collaborators.value = [...this.collaborators.value, data.user]
  }

  _handleUserLeft(data) {
    this.collaborators.value = this.collaborators.value.filter(u => u.id !== data.userId)
  }

  _handleRoomUsers(data) {
    this.collaborators.value = data.users
  }

  _encodeUpdate(uint8Array) {
    return uint8ArrayToBase64(uint8Array)
  }

  _decodeUpdate(base64Str) {
    return base64ToUint8Array(base64Str)
  }
}
