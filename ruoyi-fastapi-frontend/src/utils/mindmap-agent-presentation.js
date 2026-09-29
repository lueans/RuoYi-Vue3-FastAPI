import { fromMarkdown } from 'mdast-util-from-markdown'
import { gfmTableFromMarkdown } from 'mdast-util-gfm-table'
import { gfmTable } from 'micromark-extension-gfm-table'
import { renderMindmapMarkdownAst, renderMindmapPlainText } from './mindmap-markdown-renderer.js'
import { normalizeMindMapHyperlink } from '../libs/simple-mind-map/src/utils/hyperlink.js'

// Presentation only: no canvas writes, provider calls, or inferred tool results.
export function buildAgentChatBlocks(entries = [], finalContent = '', { includePlans = true, foldRepeatedMessages = false } = {}) {
  const blocks = []
  for (const entry of entries) {
    if (!includePlans && entry.kind === 'plan') continue
    if (entry.kind === 'message') {
      const previous = blocks.at(-1)
      // Legacy records may contain both a streamed message and its wrapper.
      // Fold only adjacent exact copies after the run ends. Keep every copy
      // available: identical prose alone cannot prove duplicate execution.
      if (foldRepeatedMessages && entry.text && previous?.kind === 'message' && previous.text === entry.text) {
        previous.repeatedMessages ||= []
        previous.repeatedMessages.push({ ...entry })
      } else blocks.push({ ...entry })
      continue
    }
    let block = blocks.at(-1)
    if (block?.kind !== 'execution') {
      block = { kind: 'execution', key: `execution:${entry.key}`, entries: [] }
      blocks.push(block)
    }
    block.entries.push(entry)
  }
  const finalText = String(finalContent || '').trim()
  const messages = entries.filter(entry => entry.kind === 'message')
  // Preserve meaningful Markdown/code whitespace when comparing final output.
  const normalize = value => String(value).replace(/\r\n?/g, '\n').trim()
  const alreadyVisible = finalText && (
    messages.some(entry => normalize(entry.text) === normalize(finalText))
    || normalize(messages.map(entry => entry.text).join('')) === normalize(finalText)
    || normalize(messages.map(entry => entry.text).join('\n')) === normalize(finalText)
  )
  if (finalText && !alreadyVisible) blocks.push({ kind: 'message', key: 'final', text: finalText })
  const latestSteps = new Map()
  for (const block of blocks) {
    if (block.kind !== 'execution') continue
    block.rows = []
    for (const entry of block.entries) {
      if (!entry.step) { block.rows.push(entry); continue }
      let row = block.rows.at(-1)
      if (row?.kind !== 'step' || row.step.key !== entry.step.key) {
        row = { kind: 'step', key: `step:${entry.key}`, step: entry.step, entries: [], active: false }
        block.rows.push(row)
        const previous = latestSteps.get(entry.step.key)
        if (previous) previous.active = false
        latestSteps.set(entry.step.key, row)
      }
      row.entries.push(entry)
      row.active = entry.step.current === true
    }
  }
  return blocks
}

// Open Design's process/conclusion split, using the host lifecycle rather than
// agent-authored <done> markers. During editing, every prefix stays inside one
// stable container; only terminal trailing prose is lifted out. Discussion is
// a different contract: its answer must remain visible while streaming.
export function buildAgentTurnBlocks(entries = [], finalContent = '', { running = false, cancelled = false, failed = false, discussion = false } = {}) {
  const options = { includePlans: false, foldRepeatedMessages: !running }
  if (discussion) return buildAgentChatBlocks(entries, finalContent, options)
  const blocks = buildAgentChatBlocks(entries, running ? '' : finalContent, options)
  let boundary = blocks.length
  if (!running && !cancelled && !failed) {
    while (boundary > 0 && blocks[boundary - 1].kind === 'message') boundary--
  } else if (!running && blocks.at(-1)?.key === 'final') {
    // A host failure/interruption explanation stays visible, but partial agent
    // prose is not promoted to a completed answer.
    boundary--
  }
  const process = blocks.slice(0, boundary)
  const rows = process.flatMap(block => block.kind === 'execution' ? block.rows : [block])
  const records = process.flatMap(block => block.kind === 'execution' ? block.entries : [block])
  const conclusion = blocks.slice(boundary)
  // Some providers persist the conclusion as one response but stream it as
  // several messages. Compare only the contiguous terminal prose, preserving
  // Markdown whitespace and every source event inside the process.
  if (conclusion.length > 1 && conclusion.at(-1).key === 'final') {
    const normalize = text => String(text).replace(/\r\n?/g, '\n').trim()
    const parts = conclusion.slice(0, -1).map(block => block.text)
    if (['', '\n'].some(separator => normalize(parts.join(separator)) === normalize(conclusion.at(-1).text))) conclusion.pop()
  }
  return [
    ...(running || records.length ? [{ kind: 'execution', key: 'execution:turn', entries: records, rows }] : []),
    ...conclusion,
  ]
}

// The entire turn may recover from a failed call. Keep that evidence visible
// without asserting that the turn failed (or that the document was saved).
export function agentTurnExecutionState(entries, options = {}) {
  if (options.running || options.cancelled || options.failed) return agentExecutionState(entries, options)
  if (entries.some(entry => entry.kind === 'tool' && entry.status === 'failed')) return { label: '记录已结束 · 含失败调用', tone: 'unknown' }
  if (entries.some(entry => entry.kind === 'tool' && ['unknown', 'running', 'cancelled'].includes(entry.status))) return { label: '记录已结束 · 有调用未确认', tone: 'unknown' }
  return { label: '记录已结束', tone: 'completed' }
}

// Paginate actual records rather than groups (one step may own thousands of
// calls). Keep the original group key so streaming never resets manual folds.
export function sliceAgentExecutionRows(rows, limit) {
  let remaining = Math.max(0, Math.floor(Number.isFinite(limit) ? limit : 0))
  const result = []
  for (let index = rows.length - 1; index >= 0 && remaining > 0; index--) {
    const row = rows[index]
    if (row.kind === 'step') {
      const entries = row.entries.slice(-remaining)
      result.push({ ...row, entries })
      remaining -= entries.length
    } else { result.push(row); remaining-- }
  }
  return result.reverse()
}

export function agentStepState(step, { running = false, cancelled = false, active = false } = {}) {
  if (step.removed) return { label: '已从计划移除', tone: 'unknown' }
  if (step.status === 'in_progress') {
    if (cancelled) return { label: '已中断', tone: 'cancelled' }
    if (!running) return { label: '未确认完成', tone: 'unknown' }
    return active ? { label: '进行中', tone: 'running' } : { label: '过程记录', tone: 'unknown' }
  }
  return ({ completed: { label: '已完成', tone: 'completed' }, cancelled: { label: '已取消', tone: 'cancelled' } })[step.status]
    || { label: '待执行', tone: 'unknown' }
}

// A compact view of the latest snapshot, not a guessed percentage or an
// implicit promotion of the first pending item to "running".
export function agentPlanSummary(todos = [], { running = false, cancelled = false, failed = false } = {}) {
  if (!todos.length) return null
  const completed = todos.filter(todo => todo.status === 'completed').length
  const active = todos.filter(todo => todo.status === 'in_progress')
  const meta = `已完成 ${completed}/${todos.length} 项`
  if (completed === todos.length) return { label: '计划已完成', meta, tone: 'completed' }
  if (cancelled) return { label: '中断时的计划', meta, tone: 'cancelled' }
  if (failed) return { label: '失败时的计划', meta, tone: 'failed' }
  if (!running) return { label: '计划未全部完成', meta, tone: 'unknown' }
  if (active.length === 1) return { label: active[0].content, meta, tone: 'running' }
  if (active.length > 1) return { label: `${active.length} 项计划进行中`, meta, tone: 'running' }
  return { label: '当前任务计划', meta, tone: 'unknown' }
}

const toolLabels = {
  read_projection: ['读取', '候选脑图'], read_document_detail: ['读取', '脑图详情'],
  get_node_tags: ['读取', '节点标签'], edit_node_text: ['编辑', '节点文本'],
  edit_node_tags: ['编辑', '节点标签'], search_tags: ['搜索', '已有标签'],
  suggest_tags: ['建议', '新增标签'], add_comment: ['新增', '节点评论'],
  start_document: ['创建', '脑图草稿'], remove_nodes: ['删除', '脑图节点'],
  set_document_meta: ['更新', '标题与布局'], validate_draft: ['检查', '脑图草稿'],
  complete_artifact: ['生成', '最终脑图'],
  get_document: ['读取', '当前脑图'], read_document: ['读取', '当前脑图'],
  get_outline: ['读取', '脑图结构'], get_nodes: ['读取', '节点内容'],
  search_nodes: ['搜索', '脑图节点'], add_nodes: ['新增', '脑图节点'],
  update_nodes: ['更新', '节点内容'], delete_nodes: ['删除', '脑图节点'],
  move_nodes: ['移动', '脑图节点'], replace_document: ['更新', '整份脑图'],
  update_plan: ['更新', '任务计划'], validate_document: ['检查', '脑图结构'],
  finalize: ['完成', '脑图结果'], finish: ['完成', '脑图结果'],
}
function shortToolName(name) {
  return String(name || '').split('__').at(-1).replace(/^mindmap_/, '')
}
export function agentToolLabel(name) {
  const short = shortToolName(name)
  const label = Object.hasOwn(toolLabels, short) ? toolLabels[short] : null
  return label ? { verb: label[0], subject: label[1] } : { verb: '调用', subject: short || '工具' }
}

function toolRecord(text) {
  // Stored details are bounded and may end mid-JSON. Never infer from a
  // partially received/truncated object, nor expand arbitrary provider blobs.
  if (typeof text !== 'string' || text.length > 6000) return null
  try {
    const value = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
  } catch { return null }
}
function toolCount(value) { return Number.isSafeInteger(value) && value >= 0 ? value : null }
function toolText(value) {
  return typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) : ''
}
export function agentToolPresentation(entry) {
  const label = agentToolLabel(entry.name)
  const name = shortToolName(entry.name)
  const input = toolRecord(entry.input)
  const output = toolRecord(entry.output)
  let summary = ''
  if (entry.status === 'completed') {
    // These scalar fields are receipts, not array lengths: public detail
    // arrays contain at most 12 items. A tool receipt is NOT a save receipt.
    const receipt = ({
      add_nodes: ['createdCount', n => `工具返回：新增 ${n} 个节点`],
      update_nodes: ['updated', n => `工具返回：完成 ${n} 项节点更新`],
      edit_node_text: ['updated', n => `工具返回：完成 ${n} 项文本更新`],
      edit_node_tags: ['updated', n => `工具返回：完成 ${n} 项标签更新`],
      move_nodes: ['moved', n => `工具返回：完成 ${n} 项移动`],
      remove_nodes: ['removed', n => `工具返回：删除 ${n} 个目标（含其子树）`],
    })
    if (Object.hasOwn(receipt, name)) {
      const [field, format] = receipt[name]
      const count = toolCount(output?.[field])
      if (count !== null) summary = format(count)
    } else if (['read_projection', 'read_document_detail', 'validate_draft', 'complete_artifact'].includes(name)) {
      const count = toolCount(output?.summary?.nodeCount) ?? toolCount(output?.nodeCount) ?? toolCount(entry.scopeNodeCount)
      if (count !== null) summary = `返回的授权范围：${count} 个节点`
    }
  }
  let texts = []
  if (name === 'add_nodes' && Array.isArray(input?.nodes)) texts = input.nodes.slice(0, 2).map(node => toolText(node?.text))
  if (name === 'update_nodes' && Array.isArray(input?.updates)) texts = input.updates.slice(0, 2).map(node => toolText(node?.patch?.text))
  if (['edit_node_text', 'start_document', 'set_document_meta'].includes(name)) texts = [toolText(input?.text || input?.title)]
  if (name === 'search_tags') texts = [toolText(input?.query)]
  const preview = texts.filter(Boolean).map(text => `「${text}」`).join('、')
  const request = preview ? `请求内容预览：${preview}` : ''
  return { ...label, summary, request }
}
export function formatAgentDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`
  return `${Math.floor(ms / 60000)} m ${Math.floor((ms % 60000) / 1000)} s`
}
export function agentExecutionState(entries, { running = false, cancelled = false, failed = false } = {}) {
  if (running) return { label: '进行中', tone: 'running' }
  if (cancelled) return { label: '已中断', tone: 'cancelled' }
  if (failed || entries.some(entry => entry.kind === 'tool' && entry.status === 'failed')) return { label: '执行失败', tone: 'failed' }
  if (entries.some(entry => entry.kind === 'tool' && entry.status === 'unknown')) return { label: '记录已结束', tone: 'unknown' }
  return { label: '已完成', tone: 'completed' }
}
export function renderAgentMarkdown(value) {
  // Allowlisted AST rendering. Raw HTML stays escaped; no agent-supplied image loads.
  const source = String(value || '').slice(0, 100000)
  try {
    return renderMindmapMarkdownAst(fromMarkdown(source, {
      extensions: [gfmTable()],
      mdastExtensions: [gfmTableFromMarkdown()],
    }), {
      normalizeLink: normalizeMindMapHyperlink,
    })
  } catch {
    // The length limit cannot bound Markdown nesting. Keep provider text
    // readable if parsing/rendering overflows, without breaking future deltas.
    return renderMindmapPlainText(source)
  }
}
export function isAgentChatNearBottom(element, distance = 64) {
  return !element || element.scrollHeight - element.scrollTop - element.clientHeight <= distance
}
