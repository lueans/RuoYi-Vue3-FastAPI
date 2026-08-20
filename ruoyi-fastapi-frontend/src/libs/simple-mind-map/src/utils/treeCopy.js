const isObject = value => Boolean(value && typeof value === 'object')

// Iterative tree copy kernel used by history snapshots and node copy/paste.
// resolveNode adapts render nodes and nodeData wrappers without duplicating
// traversal behavior. Invalid cycles/shared objects keep their first position.
export const copyTreeIterative = ({
  target,
  root,
  cloneData,
  resolveNode = node => ({ dataSource: node, children: node?.children }),
  transformData = data => data
}) => {
  const outputRoot = target || {}
  const visited = new WeakSet()
  if (isObject(root)) visited.add(root)
  const stack = [{ source: root, output: outputRoot }]

  while (stack.length > 0) {
    const { source, output } = stack.pop()
    const { dataSource, children: resolvedChildren } = resolveNode(source)
    output.data = transformData(cloneData(dataSource.data), source, dataSource)
    output.children = []

    Object.keys(dataSource).forEach(key => {
      if (!['data', 'children'].includes(key) && !/^_/.test(key)) {
        output[key] = dataSource[key]
      }
    })

    const children = Array.isArray(resolvedChildren) ? resolvedChildren : []
    const childFrames = []
    for (let index = 0; index < children.length; index += 1) {
      const child = children[index]
      if (isObject(child) && visited.has(child)) continue
      if (isObject(child)) visited.add(child)
      const childOutput = {}
      output.children.push(childOutput)
      childFrames.push({ source: child, output: childOutput })
    }
    for (let index = childFrames.length - 1; index >= 0; index -= 1) {
      stack.push(childFrames[index])
    }
  }

  return outputRoot
}
