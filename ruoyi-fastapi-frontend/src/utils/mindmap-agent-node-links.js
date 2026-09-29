// Open Design record-file-open: links require positive document identity, never
// a matching name. These receipts locate current nodes; they do not prove save.
import { isBoundedText, normalizeNumericOwnerUserId } from './mindmap-ai-shared.js'
import { parseMindmapRouteId } from './mindmap-route.js'

const NODE_TOOLS = new Set(['start_document', 'add_nodes', 'update_nodes', 'move_nodes', 'edit_node_text', 'edit_node_tags', 'add_comment'])
const uid = value => isBoundedText(value, 64) ? value : ''

export function agentToolNodeTargets(entry) {
  if (entry?.status !== 'completed' || typeof entry.output !== 'string' || entry.output.length > 6000) return []
  // Exact known namespaces only; display-name suffix matching is not evidence.
  const name = typeof entry.name === 'string' ? entry.name.replace(/^(?:mcp__mindmap__|mindmap\/)/, '') : ''
  if (!NODE_TOOLS.has(name)) return []
  let result
  try { result = JSON.parse(entry.output) } catch { return [] }
  if (!result || typeof result !== 'object' || Array.isArray(result)) return []
  let values = []
  if (name === 'start_document') values = [result.rootUid]
  else if (name === 'add_nodes') values = Array.isArray(result.created) ? result.created.map(item => item?.nodeUid) : []
  else if (name === 'add_comment') values = result.accepted === true ? [result.nodeUid] : []
  else values = Array.isArray(result.nodeUids) ? result.nodeUids : []
  return [...new Set(values.filter(value => uid(value)))].slice(0, 12)
}

export function resolveAgentToolDocumentScope(candidate, { currentJob, editorContext, sourceContext, ownerUserId } = {}) {
  const owner = normalizeNumericOwnerUserId(ownerUserId)
  const jobId = candidate?.id
  const unavailable = reason => ({ reason, documentId: '', jobId: jobId || '', ownerUserId: owner })
  if (!owner || !isBoundedText(jobId, 128)) return unavailable('无法确认这条记录的任务归属。')
  if (['rejected', 'undone', 'expired'].includes(candidate?.status)) return unavailable('本轮结果已撤销、未采纳或已过期，仅保留执行记录。')
  const cloudId = parseMindmapRouteId(candidate?.sourceMindmapId)
  if (candidate?.sourceType === 'cloud_document' && cloudId) {
    if (parseMindmapRouteId(editorContext?.mindmapId) !== cloudId
      || editorContext?.documentId !== `cloud:${cloudId}`) return unavailable('这条记录属于其他脑图，请在原脑图中查看。')
    return { reason: '', documentId: `cloud:${cloudId}`, jobId, ownerUserId: owner }
  }
  if (candidate?.sourceType === 'local_snapshot' && candidate.id === currentJob?.id
    && !editorContext?.mindmapId && !sourceContext?.mindmapId
    && isBoundedText(sourceContext?.documentId, 256)
    && sourceContext.documentId === editorContext?.documentId) {
    return { reason: '', documentId: sourceContext.documentId, jobId, ownerUserId: owner }
  }
  return unavailable('无法确认结果与当前画布属于同一份脑图；请在对应结果中查看。')
}

// Read-only, synchronous camera operation. Busy/hidden nodes are not expanded
// or retried later against a potentially different document.
export function focusMindmapToolNode({ request, ownerUserId, documentId, mindMap, previewJobId = '', blocked = false, navigate }) {
  const fail = message => ({ ok: false, message })
  if (!request || !uid(request.nodeUid) || !isBoundedText(request.jobId, 128)
    || !isBoundedText(request.documentId, 256)
    || !normalizeNumericOwnerUserId(ownerUserId)
    || request.ownerUserId !== normalizeNumericOwnerUserId(ownerUserId)
    || request.documentId !== documentId) return fail('脑图或账号已经变化，请重新打开对应记录。')
  if (previewJobId && request.jobId !== previewJobId) return fail('画布正在显示另一轮预览，请处理当前预览后重试。')
  const renderer = mindMap?.renderer
  if (blocked || !renderer || renderer.isRendering || renderer.renderTimer
    || typeof renderer.findNodeByUid !== 'function' || typeof renderer.moveNodeToCenter !== 'function'
    || ![mindMap.width, mindMap.height].every(value => Number.isFinite(value) && value > 0)) return fail('画布正在同步或尚未就绪，请稍后重试定位。')
  const node = renderer.findNodeByUid(request.nodeUid)
  if (!node || node.isHide || node.group?.node?.isConnected !== true || node.group?.visible?.() === false) {
    return fail('节点当前未显示或已不存在，请展开对应分支或等待画布同步后重试。')
  }
  if (![node.left, node.top, node.width, node.height].every(Number.isFinite) || node.width <= 0 || node.height <= 0) {
    return fail('节点尚未完成布局，请稍后重试定位。')
  }
  try {
    navigate(node)
    const text = String(node.getData?.('text') || '').replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim().slice(0, 80)
    return { ok: true, message: text ? `已定位当前节点：${text}` : '已定位当前节点。' }
  } catch { return fail('暂时无法定位该节点，请稍后重试。') }
}
