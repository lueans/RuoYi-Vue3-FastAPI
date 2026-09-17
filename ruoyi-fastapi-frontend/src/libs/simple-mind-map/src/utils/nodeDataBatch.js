const MAX_NODE_DATA_BATCH_SIZE = 500

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)

function assertWritablePatch(data, patch) {
  Object.keys(patch).forEach(key => {
    const descriptor = Object.getOwnPropertyDescriptor(data, key)
    if (patch[key] === undefined) {
      if (descriptor && descriptor.configurable === false) {
        throw new TypeError(`节点字段 ${key} 无法清除`)
      }
      return
    }
    if (descriptor && 'writable' in descriptor && descriptor.writable === false) {
      throw new TypeError(`节点字段 ${key} 无法更新`)
    }
    if (!descriptor && !Object.isExtensible(data)) {
      throw new TypeError(`节点数据无法新增字段 ${key}`)
    }
  })
}

/**
 * Apply sparse node-data patches as an all-or-nothing in-memory transaction.
 * `undefined` means delete the persisted field instead of leaving an own key
 * whose value merely happens to be undefined.
 */
export function applyNodeDataBatch(updates) {
  if (!Array.isArray(updates)) throw new TypeError('批量节点更新必须是数组')
  if (updates.length > MAX_NODE_DATA_BATCH_SIZE) {
    throw new RangeError(`单次最多更新 ${MAX_NODE_DATA_BATCH_SIZE} 个节点`)
  }

  const prepared = []
  const seenNodeData = new Set()
  updates.forEach((update, index) => {
    const node = update?.node
    const data = node?.nodeData?.data
    const patch = update?.patch
    if (!node || !data || typeof data !== 'object' || Array.isArray(data)) {
      throw new TypeError(`第 ${index + 1} 个节点不可更新`)
    }
    if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
      throw new TypeError(`第 ${index + 1} 个节点补丁无效`)
    }
    if (seenNodeData.has(data)) throw new TypeError('同一节点不能在批量命令中重复更新')
    seenNodeData.add(data)
    assertWritablePatch(data, patch)
    prepared.push({
      data,
      patch,
      snapshot: Object.keys(patch).map(key => ({
        key,
        existed: hasOwn(data, key),
        value: data[key],
      })),
    })
  })

  const applied = []
  try {
    prepared.forEach(entry => {
      applied.push(entry)
      Object.entries(entry.patch).forEach(([key, value]) => {
        const succeeded = value === undefined
          ? Reflect.deleteProperty(entry.data, key)
          : Reflect.set(entry.data, key, value)
        if (!succeeded) throw new TypeError(`节点字段 ${key} 更新失败`)
      })
    })
  } catch (error) {
    applied.reverse().forEach(entry => {
      entry.snapshot.forEach(({ key, existed, value }) => {
        if (existed) Reflect.set(entry.data, key, value)
        else Reflect.deleteProperty(entry.data, key)
      })
    })
    throw error
  }
  return prepared.length
}
