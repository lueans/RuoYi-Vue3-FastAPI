const getValueType = value =>
  Object.prototype.toString.call(value).slice(8, -1)

const isContainerType = type => type === 'Object' || type === 'Array'

const pairWasVisited = (visitedPairs, left, right) => {
  let rightValues = visitedPairs.get(left)
  if (rightValues?.has(right)) return true
  if (!rightValues) {
    rightValues = new WeakSet()
    visitedPairs.set(left, rightValues)
  }
  rightValues.add(right)
  return false
}

// Stack-safe structural equality for the JSON-like node and collaboration
// data used by simple-mind-map. Non-container values intentionally retain the
// original strict-equality behavior (including NaN and Date instances).
export const isSameObject = (left, right) => {
  const stack = [{ left, right }]
  const visitedPairs = new WeakMap()

  while (stack.length > 0) {
    const pair = stack.pop()
    if (pair.left === pair.right) continue

    const leftType = getValueType(pair.left)
    if (leftType !== getValueType(pair.right)) return false
    if (!isContainerType(leftType)) return false
    if (pairWasVisited(visitedPairs, pair.left, pair.right)) continue

    if (leftType === 'Array') {
      if (pair.left.length !== pair.right.length) return false
      for (let index = pair.left.length - 1; index >= 0; index -= 1) {
        stack.push({ left: pair.left[index], right: pair.right[index] })
      }
      continue
    }

    const leftKeys = Object.keys(pair.left)
    const rightKeys = Object.keys(pair.right)
    if (leftKeys.length !== rightKeys.length) return false
    for (let index = leftKeys.length - 1; index >= 0; index -= 1) {
      const key = leftKeys[index]
      if (!Object.prototype.hasOwnProperty.call(pair.right, key)) return false
      stack.push({ left: pair.left[key], right: pair.right[key] })
    }
  }

  return true
}
