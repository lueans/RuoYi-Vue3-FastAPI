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

export class YjsMindmapSync {
  constructor(mindmapId, mindMapInstance) {
    this.mindmapId = mindmapId
    this.mindMap = mindMapInstance
    this.doc = new Y.Doc()
    this.collaborators = ref([])
    this.isSynced = ref(false)
    this._applyingRemote = false

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
      if (origin !== 'remote') {
        this.wsClient.send({
          type: 'update',
          update: this._encodeUpdate(update),
          state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
        })
      }
    })

    // 监听节点变更 → 同步到脑图实例
    this.yNodes.observeDeep(() => {
      if (!this._applyingRemote && this.mindMap) {
        this._applyYjsToMindmap()
      }
    })

    this.wsClient.connect()
  }

  destroy() {
    this.wsClient.disconnect()
    this.doc.destroy()
  }

  /** 将当前脑图数据写入 Yjs（初始化时调用） */
  initFromMindmap(nodeTree) {
    const flat = {}
    flattenTree(nodeTree, null, flat)

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
    })
  }

  /** 监听 simple-mind-map 的 data_change_detail 事件，翻译为 Yjs 操作 */
  onDataChangeDetail(detailList) {
    if (!detailList || !detailList.length) return

    this.doc.transact(() => {
      for (const detail of detailList) {
        const uid = detail.data?.uid || detail.oldData?.uid
        if (!uid) continue

        switch (detail.action) {
          case 'create': {
            const yNode = new Y.Map()
            const yData = new Y.Map()
            for (const [k, v] of Object.entries(detail.data.data || {})) {
              yData.set(k, v)
            }
            yNode.set('data', yData)
            yNode.set('children', Y.Array.from(
              (detail.data.children || []).map(c => c.data?.uid).filter(Boolean)
            ))
            yNode.set('parentUid', '')
            this.yNodes.set(uid, yNode)

            // 更新父节点的 children
            // 找到父节点 — 简单策略：遍历找不包含此 uid 的节点
            // TODO: 从 detail 中获取父节点信息更高效
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
            }
            break
          }

          case 'delete': {
            this.yNodes.delete(uid)
            break
          }
        }
      }
    })
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
        this.mindMap.setData(tree)
      }
    } finally {
      this._applyingRemote = false
    }
  }

  _handleSyncInit(data) {
    const state = this._decodeUpdate(data.state)
    Y.applyUpdate(this.doc, state, 'remote')
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
    return btoa(String.fromCharCode(...uint8Array))
  }

  _decodeUpdate(base64Str) {
    return Uint8Array.from(atob(base64Str), c => c.charCodeAt(0))
  }
}
