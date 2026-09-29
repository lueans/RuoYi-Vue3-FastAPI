// Camera motion is independent of draft playback. Never change zoom, expansion,
// document data or history to make an AI update visible.
export function panMindmapAiNodeIntoView(map, node) {
  const t = map?.draw?.transform()
  if (!node || !t || typeof map?.view?.translateXY !== 'function') return false
  const values = [map.width, map.height, node.left, node.top, node.width, node.height,
    t.scaleX, t.scaleY, t.translateX, t.translateY]
  if (!values.every(Number.isFinite) || map.width <= 0 || map.height <= 0
    || t.scaleX <= 0 || t.scaleY <= 0 || node.width < 0 || node.height < 0) return false
  function offset(start, size, extent) {
    const padding = Math.min(48, extent / 4)
    const end = extent - padding
    const delta = size > end - padding ? padding - start
      : start < padding ? padding - start : start + size > end ? end - start - size : 0
    return Math.abs(delta) < 1 ? 0 : delta
  }
  const dx = offset(node.left * t.scaleX + t.translateX, node.width * t.scaleX, map.width)
  const dy = offset(node.top * t.scaleY + t.translateY, node.height * t.scaleY, map.height)
  if (dx || dy) map.view.translateXY(dx, dy)
  return true
}

export function createMindmapAiCamera({ getMindmap, getSession, onFollowingChange = () => {},
  setTimer = setTimeout, clearTimer = clearTimeout }) {
  let owner = null
  let following = false
  let targetUid = ''
  let timer = null
  let moving = false
  let disposed = false
  let attempts = 0
  const current = () => owner && owner.map === getMindmap() && owner.session === getSession()
  function cancel() {
    if (timer !== null) clearTimer(timer)
    timer = null
  }
  function pause() {
    cancel()
    if (following) { following = false; onFollowingChange(false) }
  }
  function onViewChange() { if (!moving) pause() }
  function reset() {
    pause()
    owner?.map.off?.('view_data_change', onViewChange)
    owner = null
    targetUid = ''
    attempts = 0
  }
  function bind() {
    if (disposed) return false
    if (current()) return true
    reset()
    const map = getMindmap(), session = getSession()
    if (!map || !session?.jobId) return false
    owner = { map, session }
    map.on?.('view_data_change', onViewChange)
    return true
  }
  function schedule(delay = 100) {
    if (timer !== null || !following || !targetUid || disposed) return
    timer = setTimer(flush, delay)
  }
  function flush() {
    timer = null
    if (disposed || !current()) { reset(); return }
    if (!following) return
    const map = owner.map
    if (map.renderer?.isRendering || map.renderer?.renderTimer) {
      if (++attempts < 20) schedule(40)
      return
    }
    try {
      moving = true
      if (!panMindmapAiNodeIntoView(map, map.renderer?.findNodeByUid?.(targetUid))) {
        if (++attempts < 20) schedule(40)
      } else attempts = 0
    } catch {
      // A failed camera lookup must never abort the document's playback ACK.
      pause()
    } finally { moving = false }
  }
  function focus(payload = {}) {
    const session = getSession()
    // History restoration has no authority to move the current canvas.
    if (!session || String(payload.jobId || '') !== session.jobId || !bind()) return
    const uid = Array.isArray(payload.nodeUids) ? String(payload.nodeUids.at(-1) || '').trim() : ''
    if (!uid || uid.length > 64) return
    targetUid = uid
    attempts = 0
    schedule()
  }
  function setFollowing(value) {
    if (!bind()) return false
    if (!value) { pause(); return false }
    if (!following) { following = true; onFollowingChange(true) }
    attempts = 0
    schedule(0)
    return true
  }
  return { focus, setFollowing, pause, reset, dispose() { reset(); disposed = true } }
}
