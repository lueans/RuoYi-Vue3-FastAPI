const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)

const assignValue = (target, key, value) => {
  if (Array.isArray(target)) {
    target[key] = value
    return
  }
  Object.defineProperty(target, key, {
    value,
    enumerable: true,
    configurable: true,
    writable: true
  })
}

const normalizePrimitive = value => {
  if (typeof value !== 'number') return value
  if (!Number.isFinite(value)) return null
  return Object.is(value, -0) ? 0 : value
}

const prepareJsonValue = (value, jsonKey) => {
  if (
    value !== null
    && (typeof value === 'object' || typeof value === 'bigint')
    && typeof value.toJSON === 'function'
  ) {
    value = value.toJSON(jsonKey)
  }
  if (value !== null && typeof value === 'object') {
    const type = Object.prototype.toString.call(value)
    if (
      type === '[object Boolean]'
      || type === '[object BigInt]'
      || type === '[object Number]'
      || type === '[object String]'
    ) return value.valueOf()
  }
  return value
}

// 与 JSON.parse(JSON.stringify(value)) 面向文档数据的语义一致，但使用
// 显式进入/退出帧，避免合法深树耗尽 JavaScript 调用栈。
export const cloneJsonValueIterative = input => {
  const resultHolder = {}
  const activePath = new WeakSet()
  const stack = [{
    type: 'value',
    value: input,
    target: resultHolder,
    targetKey: 'value',
    jsonKey: '',
    arrayItem: false
  }]

  try {
    while (stack.length > 0) {
      const frame = stack.pop()
      if (frame.type === 'exit') {
        activePath.delete(frame.value)
        continue
      }

      let value = frame.source
        ? frame.source[frame.sourceKey]
        : frame.value
      value = prepareJsonValue(value, frame.jsonKey)

      const valueType = typeof value
      if (value === null || valueType === 'string' || valueType === 'boolean') {
        assignValue(frame.target, frame.targetKey, value)
        continue
      }
      if (valueType === 'number') {
        assignValue(frame.target, frame.targetKey, normalizePrimitive(value))
        continue
      }
      if (
        valueType === 'undefined'
        || valueType === 'function'
        || valueType === 'symbol'
      ) {
        if (frame.arrayItem) assignValue(frame.target, frame.targetKey, null)
        continue
      }
      if (valueType === 'bigint') throw new TypeError('BigInt is not JSON serializable')
      if (valueType !== 'object') continue
      if (activePath.has(value)) throw new TypeError('Cyclic JSON value')

      const target = Array.isArray(value) ? [] : {}
      assignValue(frame.target, frame.targetKey, target)
      activePath.add(value)
      stack.push({ type: 'exit', value })

      if (Array.isArray(value)) {
        for (let index = value.length - 1; index >= 0; index -= 1) {
          stack.push({
            type: 'value',
            source: value,
            sourceKey: index,
            target,
            targetKey: index,
            jsonKey: String(index),
            arrayItem: true
          })
        }
        continue
      }

      const keys = Object.keys(value)
      for (let index = keys.length - 1; index >= 0; index -= 1) {
        const key = keys[index]
        stack.push({
          type: 'value',
          source: value,
          sourceKey: key,
          target,
          targetKey: key,
          jsonKey: key,
          arrayItem: false
        })
      }
    }
  } catch {
    return null
  }

  return hasOwn(resultHolder, 'value') ? resultHolder.value : null
}

const normalizeJsonIndent = space => {
  if (space !== null && typeof space === 'object') {
    const type = Object.prototype.toString.call(space)
    if (type === '[object Number]' || type === '[object String]') {
      space = space.valueOf()
    }
  }
  if (typeof space === 'number') {
    if (Number.isNaN(space) || space <= 0) return ''
    const size = space === Infinity ? 10 : Math.min(10, Math.trunc(space))
    return ' '.repeat(size)
  }
  return typeof space === 'string' ? space.slice(0, 10) : ''
}

const appendValuePrefix = (chunks, frame, rootState, indent) => {
  if (frame.context === 'root') {
    rootState.hasValue = true
    return
  }
  if (frame.context === 'array') {
    if (frame.index > 0) chunks.push(',')
    if (indent) chunks.push('\n', indent.repeat(frame.depth))
    return
  }
  if (frame.objectState.hasValue) chunks.push(',')
  frame.objectState.hasValue = true
  if (indent) chunks.push('\n', indent.repeat(frame.depth))
  chunks.push(JSON.stringify(frame.jsonKey), indent ? ': ' : ':')
}

// JSON.stringify 的文档语义实现。仅把字符串和键的转义交给
// 原生序列化器，容器展开、循环检测和输出顺序全部由显式帧维护。
export const stringifyJsonValueIterative = (input, space = '') => {
  const chunks = []
  const activePath = new WeakSet()
  const rootState = { hasValue: false }
  const indent = normalizeJsonIndent(space)
  const stack = [{
    type: 'value',
    value: input,
    context: 'root',
    jsonKey: '',
    depth: 0
  }]

  while (stack.length > 0) {
    const frame = stack.pop()
    if (frame.type === 'exit') {
      if (indent && frame.hasChildren()) {
        chunks.push('\n', indent.repeat(frame.depth))
      }
      chunks.push(frame.closingToken)
      activePath.delete(frame.value)
      continue
    }

    let value = frame.source
      ? frame.source[frame.sourceKey]
      : frame.value
    value = prepareJsonValue(value, frame.jsonKey)
    let valueType = typeof value
    if (
      valueType === 'undefined'
      || valueType === 'function'
      || valueType === 'symbol'
    ) {
      if (frame.context !== 'array') continue
      value = null
      valueType = 'object'
    }
    if (valueType === 'bigint') throw new TypeError('BigInt is not JSON serializable')

    appendValuePrefix(chunks, frame, rootState, indent)
    if (
      value === null
      || valueType === 'string'
      || valueType === 'boolean'
      || valueType === 'number'
    ) {
      chunks.push(JSON.stringify(normalizePrimitive(value)))
      continue
    }
    if (valueType !== 'object') continue
    if (activePath.has(value)) throw new TypeError('Cyclic JSON value')
    activePath.add(value)

    const isArray = Array.isArray(value)
    const length = isArray ? value.length : 0
    const objectState = isArray ? null : { hasValue: false }
    chunks.push(isArray ? '[' : '{')
    stack.push({
      type: 'exit',
      value,
      closingToken: isArray ? ']' : '}',
      depth: frame.depth,
      hasChildren: isArray
        ? () => length > 0
        : () => objectState.hasValue
    })

    if (isArray) {
      for (let index = length - 1; index >= 0; index -= 1) {
        stack.push({
          type: 'value',
          source: value,
          sourceKey: index,
          context: 'array',
          jsonKey: String(index),
          index,
          depth: frame.depth + 1
        })
      }
      continue
    }

    const keys = Object.keys(value)
    for (let index = keys.length - 1; index >= 0; index -= 1) {
      const key = keys[index]
      stack.push({
        type: 'value',
        source: value,
        sourceKey: key,
        context: 'object',
        jsonKey: key,
        objectState,
        depth: frame.depth + 1
      })
    }
  }

  return rootState.hasValue ? chunks.join('') : undefined
}
