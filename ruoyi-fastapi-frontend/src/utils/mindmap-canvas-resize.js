// CSS split resizing does not emit window.resize. Coalesce actual container
// geometry changes and never ask the renderer to size a detached/hidden canvas.
export function createMindmapCanvasResize({ getElement, getMindmap,
  requestFrame = callback => requestAnimationFrame(callback),
  cancelFrame = id => cancelAnimationFrame(id) }) {
  let frame = null
  let disposed = false
  function schedule() {
    if (disposed || frame !== null) return
    frame = requestFrame(() => {
      frame = null
      if (disposed) return
      const element = getElement()
      const mindmap = getMindmap()
      if (!element?.isConnected || !mindmap || mindmap.el !== element) return
      const { width, height } = element.getBoundingClientRect()
      if (width > 0 && height > 0) mindmap.resize()
    })
  }
  function dispose() {
    disposed = true
    if (frame !== null) cancelFrame(frame)
    frame = null
  }
  return { schedule, dispose }
}
