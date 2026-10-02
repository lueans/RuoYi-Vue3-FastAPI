import { isRecord } from './mindmap-ai-shared.js'
import { canonicalMindmapJson } from './mindmap-ai-artifact.js'
import { CONSTANTS } from '../libs/simple-mind-map/src/constants/constant.js'

// Match the server-owned template profile registry. These are only accepted
// through a validated proposal profile, never as free-form model fields.
export const MINDMAP_AI_TEMPLATE_STYLE_FIELDS = Object.freeze([
  'shape', 'fillColor', 'gradientStyle', 'startColor', 'endColor',
  'startDir', 'endDir', 'borderColor', 'borderWidth', 'borderDasharray',
  'borderRadius', 'color', 'fontFamily', 'fontSize', 'fontWeight',
  'fontStyle', 'textDecoration', 'textAlign', 'lineColor', 'lineWidth',
  'lineDasharray', 'showLineMarker', 'lineMarkerDir', 'lineStyle',
  'lineRadius', 'lineOffset', 'lineActiveColor', 'lineActiveWidth',
  'textAutoWrapWidth', 'textLineHeight', 'nodePaddingX', 'nodePaddingY',
  'imgPlacement', 'imgSize', 'iconSize', 'iconColor', 'tagPlacement',
  'hoverRectColor', 'hoverRectRadius', 'generalizationLineWidth',
  'generalizationLineColor', 'associativeLineColor',
  'associativeLineWidth', 'associativeLineActiveColor',
  'associativeLineActiveWidth', 'associativeLineTextColor',
  'associativeLineTextFontSize', 'associativeLineTextLineHeight',
  'associativeLineTextFontFamily', 'paddingX', 'paddingY', 'dir',
])
export const MINDMAP_AI_TEMPLATE_FORMAT_FIELDS = Object.freeze([
  ...MINDMAP_AI_TEMPLATE_STYLE_FIELDS, 'aiTemplateRole',
])
const styleFields = new Set(MINDMAP_AI_TEMPLATE_STYLE_FIELDS)
const layouts = new Set(Object.values(CONSTANTS.LAYOUT))
const themeGroups = new Set(['root', 'second', 'node', 'generalization'])
const themeFields = new Set([...styleFields, 'backgroundColor', 'lineFlow', 'lineFlowDuration', 'lineFlowForward',
  'rootLineKeepSameInCurve', 'rootLineStartPositionKeepSameInCurve', 'generalizationLineMargin',
  'generalizationNodeMargin', 'associativeLineDasharray', 'nodeUseLineStyle', 'outerFramePaddingX', 'outerFramePaddingY'])
const placements = new Set(['left', 'right', 'top', 'bottom'])
const aligns = new Set([...placements, 'center'])
const has = (value, key) => Object.prototype.hasOwnProperty.call(value, key)
const sameValue = (left, right) => left === right || canonicalMindmapJson(left) === canonicalMindmapJson(right)

function invalidProfile(message) {
  const error = new Error(message)
  error.code = 'AI_PROPOSAL_INVALID'
  return error
}

function safeScalar(value) {
  if (typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value) && Math.abs(value) <= 10_000
  return typeof value === 'string' && value.length <= 1024
    && !/url\s*\(|javascript:|[<>\u0000-\u0008\u000b\u000c\u000e-\u001f]/i.test(value)
}

export function assertMindmapAiTemplateProfile(profile) {
  if (profile == null) return null
  if (!isRecord(profile) || profile.version !== 1 || typeof profile.profileId !== 'string' || !/^[a-f0-9]{16}$/.test(profile.profileId)
    || !isRecord(profile.roles) || !Object.keys(profile.roles).length
    || Object.keys(profile.roles).length > 2000) throw invalidProfile('提案模版格式信息无效')
  if (!layouts.has(profile.layout) || !isRecord(profile.theme) || !isRecord(profile.theme.config)
    || typeof profile.theme.template !== 'string' || !profile.theme.template || profile.theme.template.length > 100
    || Object.keys(profile.theme).some(key => !['template', 'config'].includes(key))) throw invalidProfile('提案模版文档样式无效')
  for (const [field, value] of Object.entries(profile.theme.config)) {
    if (themeGroups.has(field)) assertStyle(value)
    else if (!themeFields.has(field) || !safeScalar(value)) throw invalidProfile('提案模版主题包含不支持的样式')
  }
  for (const [id, role] of Object.entries(profile.roles)) {
    if (!/^r(?:\.[0-9]+){0,31}$/.test(id) || !isRecord(role)
      || role.parentRole !== (id === 'r' ? null : id.slice(0, id.lastIndexOf('.')))
      || (role.parentRole !== null && !has(profile.roles, role.parentRole))) {
      throw invalidProfile('提案模版角色无效')
    }
    assertStyle(role.style)
    if (!Array.isArray(role.tags) || role.tags.length > 50) throw invalidProfile('提案模版标签无效')
    const ids = new Set()
    for (const tag of role.tags) {
      if (!isRecord(tag) || !Number.isSafeInteger(tag.tagId) || tag.tagId <= 0 || ids.has(tag.tagId)
        || Object.keys(tag).some(key => !['tagId', 'placement', 'align'].includes(key))
        || (has(tag, 'placement') && !placements.has(tag.placement))
        || (has(tag, 'align') && !aligns.has(tag.align))) throw invalidProfile('提案模版标签无效')
      ids.add(tag.tagId)
    }
  }
  return profile
}

function assertStyle(style) {
  if (!isRecord(style)) throw invalidProfile('提案模版包含不支持的样式')
  for (const [field, value] of Object.entries(style)) {
    if (!styleFields.has(field) || !safeScalar(value)) throw invalidProfile('提案模版包含不支持的样式')
  }
}

function roleId(data, profile) {
  const prefix = `${profile?.profileId}:`
  const marker = data?.aiTemplateRole
  if (typeof marker !== 'string' || !marker.startsWith(prefix)) return null
  const id = marker.slice(prefix.length)
  return has(profile.roles, id) ? id : null
}

export function assertMindmapAiTemplateNodeFormat(data, previous, profile) {
  const changed = MINDMAP_AI_TEMPLATE_FORMAT_FIELDS.filter(key => (
    has(data, key) !== has(previous, key) || !sameValue(data[key], previous[key])
  ))
  if (!changed.length) return
  const id = profile && roleId(data, profile)
  if (!id) throw invalidProfile('样式修改缺少本轮可信模版角色')
  const expected = { ...previous }
  // Applying a role replaces the node's inline format, including values left
  // by another template. Unchanged historical format takes the return above.
  for (const field of MINDMAP_AI_TEMPLATE_STYLE_FIELDS) delete expected[field]
  Object.assign(expected, profile.roles[id].style, { aiTemplateRole: `${profile.profileId}:${id}` })
  for (const [field, value] of Object.entries(profile.roles[id].style)) {
    if (!has(data, field) || data[field] !== value) throw invalidProfile('节点未完整应用本轮模版样式')
  }
  for (const key of MINDMAP_AI_TEMPLATE_FORMAT_FIELDS) {
    if (has(data, key) !== has(expected, key) || !sameValue(data[key], expected[key])) {
      throw invalidProfile('节点样式与本轮可信模版不一致')
    }
  }
}

export function assertMindmapAiTemplateDocumentMeta(payload, profile) {
  if (!profile) return
  for (const field of ['layout', 'theme']) {
    if (payload.unset.includes(field) || (has(payload.set, field)
      && canonicalMindmapJson(payload.set[field]) !== canonicalMindmapJson(profile[field]))) {
      throw invalidProfile('文档样式与本轮可信模版不一致')
    }
  }
}

export function assertMindmapAiTemplateDocumentFormat(document, previousDocument, profile) {
  if (!profile) return
  const previous = new Map()
  const oldNodes = [{ node: previousDocument.root, parent: null }]
  while (oldNodes.length) {
    const { node, parent } = oldNodes.pop()
    previous.set(String(node.data.uid), {
      data: node.data,
      parentUid: parent ? String(parent.uid) : null,
      parentTemplateRole: parent?.aiTemplateRole,
    })
    oldNodes.push(...node.children.map(child => ({ node: child, parent: node.data })))
  }
  const pending = [{ node: document.root, parent: null }]
  const parentRoles = new Set(Object.values(profile.roles).map(role => role.parentRole))
  while (pending.length) {
    const { node, parent } = pending.pop()
    const before = previous.get(String(node.data.uid))
    const oldData = before?.data || {}
    assertMindmapAiTemplateNodeFormat(node.data, oldData, profile)
    const id = roleId(node.data, profile)
    if (id) {
      const parentId = roleId(parent, profile)
      const role = profile.roles[id]
      const sameRole = node.data.aiTemplateRole === oldData.aiTemplateRole
      const relationUnchanged = before && sameRole
        && before.parentUid === (parent ? String(parent.uid) : null)
        && before.parentTemplateRole === parent?.aiTemplateRole
      // Users may have reorganized/tagged the source since its first template
      // application. Only a new role or a changed edge must match this profile.
      if (!relationUnchanged) {
        if (parent === null && role.parentRole !== null) {
          throw invalidProfile('脑图根节点必须使用模版根角色')
        }
        if (parentId && role.parentRole !== parentId && !(id === parentId && !parentRoles.has(id))) {
          throw invalidProfile('模版节点角色与父节点关系不匹配')
        }
      }
      const allowedTags = new Map(role.tags.map(tag => [tag.tagId, tag]))
      const tagsUnchanged = before && sameRole && sameValue(node.data.tag ?? null, oldData.tag ?? null)
      for (const tag of tagsUnchanged ? [] : node.data.tag || []) {
        const reference = isRecord(tag) && allowedTags.get(tag.tagId)
        if (!reference) throw invalidProfile('节点标签不属于选定模版角色')
        const oldTag = (oldData.tag || []).find(item => isRecord(item) && item.tagId === tag.tagId) || {}
        for (const key of ['placement', 'align']) {
          if (tag[key] !== (has(reference, key) ? reference[key] : oldTag[key])) {
            throw invalidProfile('节点标签位置与选定模版角色不一致')
          }
        }
      }
    }
    pending.push(...node.children.map(child => ({ node: child, parent: node.data })))
  }
}
