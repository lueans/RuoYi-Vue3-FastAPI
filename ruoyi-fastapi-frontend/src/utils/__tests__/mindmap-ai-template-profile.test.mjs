import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { MINDMAP_AI_TEMPLATE_STYLE_FIELDS } from '../mindmap-ai-template-profile.js'
import { strictApplyMindmapAiProposal, verifyMindmapAiLocalProposal } from '../mindmap-ai-proposal.js'
import { computeMindmapDocumentHash, normalizeMindmapAiSourceSnapshot } from '../mindmap-ai-artifact.js'
import { nextMindmapAiDraftFrame } from '../mindmap-ai-live-preview.js'
import { CONSTANTS } from '../../libs/simple-mind-map/src/constants/constant.js'

const profile = {
  version: 1, profileId: '0123456789abcdef', layout: 'mindMap',
  theme: { template: 'default', config: { backgroundColor: '#eeeeff', root: { fillColor: '#203040' } } },
  roles: {
    r: { parentRole: null, tags: [], style: { fillColor: '#203040', color: '#ffffff', fontSize: 28, shape: 'roundedRectangle' } },
    'r.0': { parentRole: 'r', tags: [{ tagId: 7 }], style: { fillColor: '#ddeeff', color: '#123456', borderWidth: 2, borderColor: '#abcdef', paddingX: 20, dir: 'left' } },
    'r.1': { parentRole: 'r', tags: [{ tagId: 7 }], style: { color: '#440000', fontSize: 18 } },
  },
}
const marker = role => `${profile.profileId}:${role}`
function baseDocument() {
  return { root: { data: { uid: 'root', text: '项目', expand: true }, children: [] },
    layout: 'logicalStructure', theme: { template: 'default', config: {} }, view: null, documentData: {} }
}
function operations() {
  return [
    { type: 'update_node', nodeUid: 'root', payload: {
      set: { ...profile.roles.r.style, aiTemplateRole: marker('r') }, unset: [],
    } },
    { type: 'create_node', nodeUid: 'child', payload: { parentUid: 'root', index: 0, data: {
      uid: 'child', text: '计划', ...profile.roles['r.0'].style, aiTemplateRole: marker('r.0'),
      tag: [{ tagId: 7, text: '紧急', style: { fill: '#ff8800', color: '#fff', placement: 'top', align: 'left' } }],
    } } },
    { type: 'set_document_meta', nodeUid: null, payload: { set: { layout: profile.layout, theme: profile.theme }, unset: [] } },
  ]
}

test('client trusted-template style registry matches the canonical server codec', () => {
  const codec = readFileSync(new URL('../../../../ruoyi-fastapi-backend/module_mindmap/service/simple_mind_document_codec.py', import.meta.url), 'utf8')
  const styleSet = codec.match(/\nSTYLE_KEYS = \{([\s\S]*?)\n\}/)[1]
  const fields = [...styleSet.matchAll(/'([^']+)'/g)].map(match => match[1])
  assert.deepEqual([...MINDMAP_AI_TEMPLATE_STYLE_FIELDS].sort(), [...fields, 'paddingX', 'paddingY', 'dir'].sort())
})

test('every server-supported template layout can be verified and applied locally', async () => {
  const codec = readFileSync(new URL('../../../../ruoyi-fastapi-backend/module_mindmap/ai/document.py', import.meta.url), 'utf8')
  const layoutEnum = codec.match(/class AiMindmapLayout\(str, Enum\):([\s\S]*?)\n\nAI_ALLOWED_LAYOUTS/)[1]
  const layouts = [...layoutEnum.matchAll(/= '([^']+)'/g)].map(match => match[1])
  assert.deepEqual(layouts.toSorted(), Object.values(CONSTANTS.LAYOUT).toSorted())
  for (const layout of layouts) {
    const templateProfile = { ...structuredClone(profile), layout }
    const changes = operations()
    changes.at(-1).payload.set.layout = layout
    const base = baseDocument()
    const target = strictApplyMindmapAiProposal(base, changes, { templateProfile })
    const resultHash = await computeMindmapDocumentHash(target)
    const verified = await verifyMindmapAiLocalProposal({
      baseDocument: base, operations: changes, baseHash: await computeMindmapDocumentHash(normalizeMindmapAiSourceSnapshot(base)),
      resultHash, artifactHash: resultHash, artifactDocument: target, templateProfile,
    })
    assert.equal(verified.document.layout, layout)
    assert.deepEqual(strictApplyMindmapAiProposal(base, [], { templateProfile }), base,
      'an unchanged branch also accepts the full template layout registry')
  }
})

test('verified template proposal retains node and tag styles, hierarchy, layout and theme through local apply and playback', async () => {
  const base = baseDocument()
  const target = strictApplyMindmapAiProposal(base, operations(), { templateProfile: profile })
  const normalizedBase = normalizeMindmapAiSourceSnapshot(base)
  const resultHash = await computeMindmapDocumentHash(target)
  const verified = await verifyMindmapAiLocalProposal({
    baseDocument: base, operations: operations(), baseHash: await computeMindmapDocumentHash(normalizedBase),
    resultHash, artifactHash: resultHash, artifactDocument: target, templateProfile: profile,
  })
  assert.deepEqual(verified.document, target)
  assert.equal(base.root.children.length, 0)
  let current = base
  for (let i = 0; i < 100; i++) {
    const frame = nextMindmapAiDraftFrame(current, target)
    current = frame.document
    if (frame.remaining === 0) break
  }
  assert.deepEqual(current.root, target.root)
  assert.equal(current.layout, base.layout, 'playback keeps the existing layout until authoritative apply')
  assert.deepEqual(current.theme, base.theme)
  assert.equal(verified.document.layout, profile.layout)
  assert.deepEqual(verified.document.theme, profile.theme)
  assert.deepEqual(current.root.children[0].data.tag, target.root.children[0].data.tag)
})

test('styles still require an exact profile role and cannot authorize unrelated fields', () => {
  const base = baseDocument()
  assert.throws(() => strictApplyMindmapAiProposal(base, operations()), /不允许|无效字段/)
  for (const patch of [
    { fillColor: '#badbad' }, { aiTemplateRole: 'ffffffffffffffff:r' },
    { aiTemplateRole: marker('missing') }, { image: 'https://untrusted/image.png' },
  ]) {
    const edited = operations()
    Object.assign(edited[0].payload.set, patch)
    assert.throws(() => strictApplyMindmapAiProposal(base, edited, { templateProfile: profile }))
  }
  const unsafeProfile = structuredClone(profile)
  unsafeProfile.roles.r.style.fillColor = 'url(javascript:evil)'
  assert.throws(() => strictApplyMindmapAiProposal(base, operations(), { templateProfile: unsafeProfile }), /不支持的样式/)
  const wrongTheme = operations()
  wrongTheme[2].payload.set.theme = { template: 'unexpected', config: {} }
  assert.throws(() => strictApplyMindmapAiProposal(base, wrongTheme, { templateProfile: profile }), /文档样式/)
})

test('switching template roles can remove old role styles while unmodified existing styles remain intact', () => {
  const base = strictApplyMindmapAiProposal(baseDocument(), operations(), { templateProfile: profile })
  base.root.data.fontWeight = 'bold'
  const result = strictApplyMindmapAiProposal(base, [{
    type: 'update_node', nodeUid: 'child', payload: {
      set: { ...profile.roles['r.1'].style, aiTemplateRole: marker('r.1') },
      unset: ['fillColor', 'borderWidth', 'borderColor', 'paddingX', 'dir'],
    },
  }, { type: 'update_node', nodeUid: 'root', payload: { set: { text: '新项目' }, unset: [] } }], { templateProfile: profile })
  assert.equal(result.root.children[0].data.color, '#440000')
  assert.equal(result.root.children[0].data.fillColor, undefined)
  assert.equal(result.root.data.fontWeight, 'bold')
})


test('partial role styles, wrong hierarchy and tag positions are rejected before canvas mutation', () => {
  const partial = operations()
  delete partial[0].payload.set.color
  assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), partial, { templateProfile: profile }), /未完整/)
  const wrongParent = operations()
  wrongParent[1].payload.data = { uid: 'child', text: 'invalid', ...profile.roles.r.style, aiTemplateRole: marker('r') }
  assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), wrongParent, { templateProfile: profile }), /父节点关系/)
  const wrongTag = operations()
  wrongTag[1].payload.data.tag[0].placement = 'left'
  assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), wrongTag, { templateProfile: profile }), /标签位置/)
  wrongTag[1].payload.data.tag[0].tagId = 99
  assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), wrongTag, { templateProfile: profile }), /不属于/)
  for (const mutate of [
    candidate => { candidate.layout = 'unknown' },
    candidate => { candidate.theme.config.backgroundImage = 'url(https://example.com)' },
    candidate => { candidate.theme.config.root.onClick = 'script' },
    candidate => { candidate.roles['r.0'].parentRole = 'missing' },
  ]) {
    const malformed = structuredClone(profile)
    mutate(malformed)
    assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), operations(), { templateProfile: malformed }))
  }
})


test('unmodified object-valued legacy styles survive template replay without acquiring a role', () => {
  const base = baseDocument()
  base.root.data.imgSize = { width: 80, height: 60 }
  const result = strictApplyMindmapAiProposal(base, [{ type: 'update_node', nodeUid: 'root',
    payload: { set: { text: 'Changed content' }, unset: [] } }], { templateProfile: profile })
  assert.deepEqual(result.root.data.imgSize, base.root.data.imgSize)
})

test('only the template root role may format the document root, while a partial branch can use a child role', () => {
  const rootChange = [{ type: 'update_node', nodeUid: 'root', payload: {
    set: { ...profile.roles['r.1'].style, aiTemplateRole: marker('r.1') }, unset: [],
  } }]
  assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), rootChange, { templateProfile: profile }), /根角色/)
  const branch = baseDocument()
  branch.root.children.push({ data: { uid: 'child', text: '已有分支' }, children: [] })
  rootChange[0].nodeUid = 'child'
  const result = strictApplyMindmapAiProposal(branch, rootChange, { templateProfile: profile })
  assert.equal(result.root.data.aiTemplateRole, undefined)
  assert.equal(result.root.children[0].data.aiTemplateRole, marker('r.1'))
})

test('applying a role clears all old inline format and rejects a partial cleanup', () => {
  const base = baseDocument()
  Object.assign(base.root.data, {
    fillColor: '#old', borderWidth: 9, fontWeight: 'bold', imgSize: { width: 80, height: 60 },
    aiTemplateRole: 'ffffffffffffffff:r', note: 'keep this content', customExtension: { preserved: true },
  })
  const changes = [{ type: 'update_node', nodeUid: 'root', payload: {
    set: { ...profile.roles.r.style, aiTemplateRole: marker('r') },
    unset: ['borderWidth', 'fontWeight', 'imgSize'],
  } }]
  const original = structuredClone(base)
  const result = strictApplyMindmapAiProposal(base, changes, { templateProfile: profile })
  assert.deepEqual(result.root.data, {
    uid: 'root', text: '项目', expand: true, note: 'keep this content', customExtension: { preserved: true },
    ...profile.roles.r.style, aiTemplateRole: marker('r'),
  })
  assert.deepEqual(base, original)
  for (const field of changes[0].payload.unset) {
    const partial = structuredClone(changes)
    partial[0].payload.unset = partial[0].payload.unset.filter(key => key !== field)
    assert.throws(() => strictApplyMindmapAiProposal(base, partial, { templateProfile: profile }), /样式与本轮可信模版不一致/)
  }
})

function legacyTemplateDocument() {
  const base = strictApplyMindmapAiProposal(baseDocument(), operations(), { templateProfile: profile })
  const child = base.root.children[0]
  child.children.push({ data: {
    uid: 'legacy', text: '用户移动过的节点', ...profile.roles['r.1'].style,
    aiTemplateRole: marker('r.1'), tag: [{ tagId: 99, text: '用户后来添加', placement: 'bottom' }],
  }, children: [] })
  base.root.children.push({ data: {
    uid: 'other', text: '另一个父节点', ...profile.roles['r.0'].style, aiTemplateRole: marker('r.0'),
  }, children: [] })
  return base
}

test('content-only updates preserve the existing role and user-modified source relationships and tags', () => {
  const base = legacyTemplateDocument()
  for (const nodeUid of ['root', 'child', 'legacy']) {
    const result = strictApplyMindmapAiProposal(base, [{ type: 'update_node', nodeUid,
      payload: { set: { text: 'new content' }, unset: [] } }], { templateProfile: profile })
    const legacy = result.root.children[0].children[0].data
    assert.equal(legacy.aiTemplateRole, marker('r.1'))
    assert.deepEqual(legacy.tag, base.root.children[0].children[0].data.tag)
    assert.equal(legacy.color, profile.roles['r.1'].style.color)
  }
  assert.deepEqual(strictApplyMindmapAiProposal(base, [], { templateProfile: profile }), base)
})

test('changed parent identity, parent role and new relationships still require the template hierarchy', () => {
  const base = legacyTemplateDocument()
  assert.throws(() => strictApplyMindmapAiProposal(base, [{ type: 'move_node', nodeUid: 'legacy',
    payload: { parentUid: 'other', index: 0 } }], { templateProfile: profile }), /父节点关系/,
  'moving to another parent with the same role cannot preserve an old invalid edge')

  const newChild = { type: 'create_node', nodeUid: 'new', payload: { parentUid: 'child', index: 1,
    data: { uid: 'new', text: 'new', ...profile.roles['r.1'].style, aiTemplateRole: marker('r.1') } } }
  assert.throws(() => strictApplyMindmapAiProposal(base, [newChild], { templateProfile: profile }), /父节点关系/)

  const parentChanged = baseDocument()
  parentChanged.root.children.push({ data: { uid: 'parent', text: 'unformatted parent' }, children: [{
    data: { uid: 'existing', text: 'child', ...profile.roles.r.style, aiTemplateRole: marker('r') }, children: [],
  }] })
  const applyParentRole = { type: 'update_node', nodeUid: 'parent', payload: {
    set: { ...profile.roles['r.0'].style, aiTemplateRole: marker('r.0') }, unset: [],
  } }
  assert.throws(() => strictApplyMindmapAiProposal(parentChanged, [applyParentRole], { templateProfile: profile }), /父节点关系/,
    'a changed parent role must revalidate existing children even when their parent UID is unchanged')
})

test('baseline tag exemptions do not authorize changed tags or changing the node role', () => {
  const base = legacyTemplateDocument()
  const original = structuredClone(base)
  for (const tag of [
    [{ tagId: 99, text: 'modified existing tag', placement: 'bottom' }],
    [{ tagId: 7, text: 'valid identity but invented local position', placement: 'top' }],
  ]) {
    assert.throws(() => strictApplyMindmapAiProposal(base, [{ type: 'update_node', nodeUid: 'legacy',
      payload: { set: { tag }, unset: [] } }], { templateProfile: profile }), /标签/)
  }
  const roleChange = { type: 'update_node', nodeUid: 'legacy', payload: {
    set: { ...profile.roles['r.0'].style, aiTemplateRole: marker('r.0') }, unset: ['fontSize'],
  } }
  assert.throws(() => strictApplyMindmapAiProposal(base, [roleChange], { templateProfile: profile }), /标签不属于/,
    'switching to a valid repeatable leaf role must recheck unchanged old tags')
  const permitted = strictApplyMindmapAiProposal(base, [{ type: 'update_node', nodeUid: 'legacy',
    payload: { set: { tag: [{ tagId: 7, text: 'role tag' }] }, unset: [] } }], { templateProfile: profile })
  assert.equal(permitted.root.children[0].children[0].data.tag[0].tagId, 7)
  assert.deepEqual(base, original)
})

test('an unchanged historical root role is preserved but a newly assigned invalid root role is rejected', () => {
  const base = baseDocument()
  Object.assign(base.root.data, profile.roles['r.1'].style, { aiTemplateRole: marker('r.1') })
  const contentChange = [{ type: 'update_node', nodeUid: 'root', payload: { set: { text: 'new content' }, unset: [] } }]
  assert.equal(strictApplyMindmapAiProposal(base, contentChange, { templateProfile: profile }).root.data.text, 'new content')
  const assignChildRole = [{ type: 'update_node', nodeUid: 'root', payload: {
    set: { ...profile.roles['r.1'].style, aiTemplateRole: marker('r.1') }, unset: [],
  } }]
  assert.throws(() => strictApplyMindmapAiProposal(baseDocument(), assignChildRole, { templateProfile: profile }), /根角色/)
})
