import { plainRevealText, textGraphemes } from '../libs/simple-mind-map/src/utils/textReveal.js'
import { stableJsonValue } from './mindmap-ai-shared.js'

const DEFAULT_CHARACTER_DELAY_MS = 56
const ESTIMATED_CHARACTERS_PER_NODE = 12

function nonNegativeNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : fallback
}

function documentNodes(document) {
  const result = new Map()
  const pending = document?.root ? [document.root] : []
  const visited = new WeakSet()
  while (pending.length) {
    const node = pending.pop()
    if (!node || typeof node !== 'object' || visited.has(node)) continue
    visited.add(node)
    const uid = node.data?.uid
    if (uid != null && uid !== '') result.set(String(uid), node)
    if (Array.isArray(node.children)) pending.push(...node.children)
  }
  return result
}

/** Estimate once per incoming target, then decrement on acknowledged frames. */
export function getMindmapAiPendingCharacterCount(currentDocument, targetDocument) {
  const current = documentNodes(currentDocument)
  let count = 0
  for (const [uid, target] of documentNodes(targetDocument)) {
    const previous = current.get(uid)
    const currentText = String(previous?.data?.text || '')
    const targetText = String(target.data?.text || '')
    const currentRich = previous?.data?.richText === true
    const targetRich = target.data?.richText === true
    if (previous && currentText === targetText && currentRich === targetRich) {
      // A style/empty-text operation still consumes one planner frame.
      if (JSON.stringify(stableJsonValue(previous.data)) !== JSON.stringify(stableJsonValue(target.data))) count += 1
      continue
    }
    const from = textGraphemes(plainRevealText(currentText, currentRich))
    const to = textGraphemes(plainRevealText(targetText, targetRich))
    let common = 0
    while (common < from.length && from[common] === to[common]) common += 1
    count += Math.max(1, to.length - common)
  }
  return count
}

/**
 * Playback changes speed, never ordering or completeness. The planner still
 * advances exactly one grapheme of one node per acknowledged frame, including
 * when the job has completed/cancelled. A scheduler must yield between frames;
 * zero delay is a request to keep up, not a synchronous whole-document loop.
 *
 * Callers may provide an exact character estimate obtained when a new target
 * arrives. The pending-node fallback avoids a full text scan on every tick.
 * oldestPendingAt must survive target replacements until the queue drains,
 * otherwise a fast producer can continually reset the catch-up deadline.
 */
export function getMindmapAiPlaybackPacing({
  pendingCharacters,
  pendingNodes = 0,
  oldestPendingAt,
  now = Date.now(),
  terminal = false,
} = {}) {
  const work = Math.max(
    1,
    nonNegativeNumber(pendingCharacters),
    nonNegativeNumber(pendingNodes) * ESTIMATED_CHARACTERS_PER_NODE,
  )
  const age = oldestPendingAt == null
    ? 0
    : Math.max(0, nonNegativeNumber(now) - nonNegativeNumber(oldestPendingAt, nonNegativeNumber(now)))
  const delayCap = terminal ? 16 : DEFAULT_CHARACTER_DELAY_MS
  // An aging or terminal queue gets a shorter catch-up budget. Subtract the
  // normal browser nested-timer floor rather than accumulating 56ms per letter.
  const budget = terminal ? 1000 : Math.max(400, 3000 - age / 2)
  const delayMs = Math.max(0, Math.min(delayCap, Math.floor(budget / work) - 4))
  return { delayMs }
}
