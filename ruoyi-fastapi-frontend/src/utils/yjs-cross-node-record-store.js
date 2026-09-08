/**
 * Path-addressable CRDT storage for records spanning multiple mind-map nodes.
 *
 * Fixed top-level Y.Map keys avoid shared-type identity races. Independent
 * record, JSON-path and group-member generations isolate stale pre-delete
 * writes without discarding concurrent edits to unrelated fields.
 */

import { isSameObject } from '../libs/simple-mind-map/src/utils/deepEqual.js'
import {
  cloneJsonValueIterative,
  stringifyJsonValueIterative,
} from '../libs/simple-mind-map/src/utils/jsonClone.js'
import { v5 as uuidv5 } from 'uuid'

export const CROSS_NODE_SCHEMA_VERSION = 2
export const CROSS_NODE_EPOCHS_MAP = 'crossNodeRecordEpochsV2'
export const CROSS_NODE_TOMBSTONES_MAP = 'crossNodeRecordTombstonesV2'
export const CROSS_NODE_FIELDS_MAP = 'crossNodeRecordFieldsV2'
export const CROSS_NODE_FIELD_TOMBSTONES_MAP = 'crossNodeFieldTombstonesV2'
export const CROSS_NODE_MEMBERS_MAP = 'crossNodeGroupMembersV2'
export const CROSS_NODE_MEMBER_TOMBSTONES_MAP = 'crossNodeGroupMemberTombstonesV2'

const DOMAINS = Object.freeze(['relations', 'summaries', 'groups', 'assets'])
const DOMAIN_SET = new Set(DOMAINS)
const COMPACT_PATH_PREFIX = 'p2:'
const CROSS_NODE_PATH_NAMESPACE = 'f3febf60-0f1d-594a-a706-ef547b2594d4'

function cloneValue(value) {
  if (value === undefined) return undefined
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value)
    } catch {
      // Native structuredClone implementations may recurse internally and
      // overflow on valid, deeply nested JSON. Preserve the supported JSON
      // data shape by falling back to the stack-safe document clone.
    }
  }
  const cloned = cloneJsonValueIterative(value)
  if (
    (cloned === null && value !== null && typeof value === 'object')
    || !isSameObject(cloned, value)
  ) {
    throw new TypeError('跨节点协作记录无法安全复制')
  }
  return cloned
}

function encodeAtomicValue(value) {
  let encoded
  let decoded
  try {
    encoded = stringifyJsonValueIterative(value)
    decoded = encoded === undefined ? undefined : JSON.parse(encoded)
  } catch {
    throw new TypeError('跨节点协作记录无法安全序列化')
  }
  if (encoded === undefined || !isSameObject(decoded, value)) {
    throw new TypeError('跨节点协作记录无法安全序列化')
  }
  return encoded
}

function decodeStoredValue(field) {
  if (field.valueEncoding !== 'json') {
    return { valid: true, value: cloneValue(field.value) }
  }
  try {
    return { valid: true, value: JSON.parse(field.encodedValue) }
  } catch {
    return { valid: false, value: undefined }
  }
}

function compareStableStrings(left, right) {
  left = String(left)
  right = String(right)
  return left < right ? -1 : (left > right ? 1 : 0)
}

function normalizeState(state = {}) {
  return Object.fromEntries(DOMAINS.map(domain => {
    const collection = state?.[domain]
    const entries = collection instanceof Map || typeof collection?.entries === 'function'
      ? Array.from(collection.entries())
      : Object.entries(collection || {})
    return [domain, Object.fromEntries(entries)]
  }))
}

function isPlainRecord(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function setObjectValue(target, key, value) {
  Object.defineProperty(target, key, {
    configurable: true,
    enumerable: true,
    value,
    writable: true,
  })
}

function setIfChanged(yMap, key, value) {
  if (yMap.has(key) && isSameObject(yMap.get(key), value)) return false
  yMap.set(key, cloneValue(value))
  return true
}

function encodeRecordId(domain, recordKey) {
  return JSON.stringify([domain, String(recordKey)])
}

function encodeRecordGenerationKey(domain, recordKey, generation) {
  return JSON.stringify([domain, String(recordKey), String(generation)])
}

function encodeFieldKey(domain, recordKey, recordGeneration, pathId, fieldGeneration) {
  return JSON.stringify([
    domain,
    String(recordKey),
    String(recordGeneration),
    pathId,
    String(fieldGeneration),
  ])
}

function encodeMemberKey(recordKey, recordGeneration, memberUid, memberGeneration) {
  return JSON.stringify([
    'groups',
    String(recordKey),
    String(recordGeneration),
    String(memberUid),
    String(memberGeneration),
  ])
}

function decodeTuple(value, length) {
  try {
    const tuple = JSON.parse(value)
    if (
      !Array.isArray(tuple)
      || tuple.length !== length
      || !DOMAIN_SET.has(tuple[0])
      || tuple.slice(1).some(part => typeof part !== 'string')
    ) return null
    return tuple
  } catch {
    return null
  }
}

function decodeGeneration(value) {
  if (!/^(0|[1-9]\d*)$/.test(value)) return null
  const generation = Number(value)
  return Number.isSafeInteger(generation) ? generation : null
}

function decodeFieldPath(pathId) {
  try {
    const path = JSON.parse(pathId)
    if (
      !Array.isArray(path)
      || path.length === 0
      || path.some(segment => typeof segment !== 'string')
    ) return null
    return path
  } catch {
    return null
  }
}

function encodeCompactPathId(parentPathId, segment) {
  return `${COMPACT_PATH_PREFIX}${uuidv5(
    JSON.stringify([parentPathId, segment]),
    CROSS_NODE_PATH_NAMESPACE,
  )}`
}

function isCompactPathId(pathId) {
  return typeof pathId === 'string' && pathId.startsWith(COMPACT_PATH_PREFIX)
}

function flattenRecord(record, domain) {
  const paths = new Map()
  const activePath = new WeakSet()
  const pending = Object.entries(record || {})
    .filter(([field, value]) => (
      value !== undefined
      && !(domain === 'groups' && field === 'memberUids')
    ))
    .reverse()
    .map(([segment, value]) => ({ parentPathId: null, segment, value }))
  while (pending.length) {
    const frame = pending.pop()
    if (frame.exit) {
      activePath.delete(frame.value)
      continue
    }
    const { parentPathId, segment, value } = frame
    const pathId = encodeCompactPathId(parentPathId, segment)
    if (isPlainRecord(value)) {
      if (activePath.has(value)) throw new TypeError('跨节点协作记录不能包含循环引用')
      activePath.add(value)
      paths.set(pathId, { parentPathId, segment, kind: 'object' })
      pending.push({ exit: true, value })
      const children = Object.entries(value)
      for (let index = children.length - 1; index >= 0; index -= 1) {
        const [childSegment, child] = children[index]
        if (child !== undefined) pending.push({
          parentPathId: pathId,
          segment: childSegment,
          value: child,
        })
      }
    } else {
      // Array ordering is one semantic field. Objects recurse so independent
      // style/payload leaves merge without a whole-object LWW register.
      paths.set(pathId, {
        parentPathId,
        segment,
        kind: 'value',
        encodedValue: encodeAtomicValue(value),
        valueEncoding: 'json',
      })
    }
  }
  return paths
}

function getMaps(doc) {
  return {
    recordEpochs: doc.getMap(CROSS_NODE_EPOCHS_MAP),
    recordTombstones: doc.getMap(CROSS_NODE_TOMBSTONES_MAP),
    fields: doc.getMap(CROSS_NODE_FIELDS_MAP),
    fieldTombstones: doc.getMap(CROSS_NODE_FIELD_TOMBSTONES_MAP),
    members: doc.getMap(CROSS_NODE_MEMBERS_MAP),
    memberTombstones: doc.getMap(CROSS_NODE_MEMBER_TOMBSTONES_MAP),
  }
}

function createGenerationState() {
  return { generations: new Set(), tombstones: new Set(), values: new Map() }
}

function ensureRecord(records, domain, recordKey) {
  const recordId = encodeRecordId(domain, recordKey)
  let record = records.get(recordId)
  if (!record) {
    record = {
      domain,
      recordKey,
      generations: new Set(),
      tombstones: new Set(),
      fields: new Map(),
      members: new Map(),
    }
    records.set(recordId, record)
  }
  return record
}

function ensureRecordGenerationCollection(collection, recordGeneration) {
  let result = collection.get(recordGeneration)
  if (!result) {
    result = new Map()
    collection.set(recordGeneration, result)
  }
  return result
}

function ensurePathState(record, recordGeneration, pathId) {
  const fields = ensureRecordGenerationCollection(record.fields, recordGeneration)
  let state = fields.get(pathId)
  if (!state) {
    state = createGenerationState()
    fields.set(pathId, state)
  }
  return state
}

function ensureMemberState(record, recordGeneration, memberUid) {
  const members = ensureRecordGenerationCollection(record.members, recordGeneration)
  let state = members.get(memberUid)
  if (!state) {
    state = createGenerationState()
    members.set(memberUid, state)
  }
  return state
}

function normalizeStoredField(pathId, value) {
  if (
    value
    && typeof value === 'object'
    && ['object', 'value'].includes(value.kind)
    && value.pathFormat === 2
    && typeof value.segment === 'string'
    && (
      value.parentPathId === null
      || isCompactPathId(value.parentPathId)
    )
    && (
      value.parentGeneration === null
      || (
        Number.isSafeInteger(value.parentGeneration)
        && value.parentGeneration >= 0
      )
    )
    && encodeCompactPathId(value.parentPathId, value.segment) === pathId
    && (
      value.kind === 'object'
      || (
        value.valueEncoding === 'json'
        && typeof value.encodedValue === 'string'
      )
      || Object.prototype.hasOwnProperty.call(value, 'value')
    )
  ) {
    return {
      kind: value.kind,
      ...(value.kind === 'value' && value.valueEncoding === 'json'
        ? { encodedValue: value.encodedValue, valueEncoding: 'json' }
        : {}),
      ...(value.kind === 'value' && value.valueEncoding !== 'json'
        ? { value: value.value }
        : {}),
      pathFormat: 2,
      parentPathId: value.parentPathId,
      parentGeneration: value.parentGeneration,
      segment: value.segment,
    }
  }
  const legacyPath = decodeFieldPath(pathId)
  if (
    legacyPath
    && value
    && typeof value === 'object'
    && ['object', 'value'].includes(value.kind)
    && Array.isArray(value.ancestors)
    && value.ancestors.every(Number.isSafeInteger)
  ) {
    return {
      kind: value.kind,
      ...(value.kind === 'value' ? { value: value.value } : {}),
      pathFormat: 1,
      path: legacyPath,
      ancestors: value.ancestors,
    }
  }
  if (!legacyPath) return null
  return {
    kind: 'value',
    value,
    pathFormat: 1,
    path: legacyPath,
    ancestors: [],
  }
}

function collectRawIndex(doc) {
  const maps = getMaps(doc)
  const records = new Map()
  maps.recordEpochs.forEach((active, encodedKey) => {
    const tuple = decodeTuple(encodedKey, 3)
    const generation = tuple ? decodeGeneration(tuple[2]) : null
    if (!tuple || generation === null || active !== true) return
    ensureRecord(records, tuple[0], tuple[1]).generations.add(generation)
  })
  maps.recordTombstones.forEach((deleted, encodedKey) => {
    const tuple = decodeTuple(encodedKey, 3)
    const generation = tuple ? decodeGeneration(tuple[2]) : null
    if (!tuple || generation === null || deleted !== true) return
    ensureRecord(records, tuple[0], tuple[1]).tombstones.add(generation)
  })
  maps.fields.forEach((value, encodedKey) => {
    const tuple = decodeTuple(encodedKey, 5)
    const recordGeneration = tuple ? decodeGeneration(tuple[2]) : null
    const fieldGeneration = tuple ? decodeGeneration(tuple[4]) : null
    const storedValue = tuple ? normalizeStoredField(tuple[3], value) : null
    if (
      !tuple || recordGeneration === null || !storedValue
      || fieldGeneration === null
    ) return
    const state = ensurePathState(
      ensureRecord(records, tuple[0], tuple[1]),
      recordGeneration,
      tuple[3],
    )
    state.generations.add(fieldGeneration)
    state.values.set(fieldGeneration, {
      encodedKey,
      value: storedValue,
    })
  })
  maps.fieldTombstones.forEach((deleted, encodedKey) => {
    const tuple = decodeTuple(encodedKey, 5)
    const recordGeneration = tuple ? decodeGeneration(tuple[2]) : null
    const fieldGeneration = tuple ? decodeGeneration(tuple[4]) : null
    if (
      !tuple || recordGeneration === null
      || fieldGeneration === null || deleted !== true
    ) return
    ensurePathState(
      ensureRecord(records, tuple[0], tuple[1]),
      recordGeneration,
      tuple[3],
    ).tombstones.add(fieldGeneration)
  })
  maps.members.forEach((active, encodedKey) => {
    const tuple = decodeTuple(encodedKey, 5)
    const recordGeneration = tuple ? decodeGeneration(tuple[2]) : null
    const memberGeneration = tuple ? decodeGeneration(tuple[4]) : null
    if (
      !tuple || tuple[0] !== 'groups' || recordGeneration === null
      || memberGeneration === null || active !== true
    ) return
    const state = ensureMemberState(
      ensureRecord(records, tuple[0], tuple[1]),
      recordGeneration,
      tuple[3],
    )
    state.generations.add(memberGeneration)
    state.values.set(memberGeneration, { encodedKey, value: true })
  })
  maps.memberTombstones.forEach((deleted, encodedKey) => {
    const tuple = decodeTuple(encodedKey, 5)
    const recordGeneration = tuple ? decodeGeneration(tuple[2]) : null
    const memberGeneration = tuple ? decodeGeneration(tuple[4]) : null
    if (
      !tuple || tuple[0] !== 'groups' || recordGeneration === null
      || memberGeneration === null || deleted !== true
    ) return
    ensureMemberState(
      ensureRecord(records, tuple[0], tuple[1]),
      recordGeneration,
      tuple[3],
    ).tombstones.add(memberGeneration)
  })
  return { maps, records }
}

function getHighestGeneration(state) {
  if (!state?.generations.size) return null
  return Math.max(...state.generations)
}

function getHighestActiveGeneration(state) {
  if (!state?.generations.size) return null
  let result = null
  for (const generation of state.generations) {
    if (
      !state.tombstones.has(generation)
      && (result === null || generation > result)
    ) result = generation
  }
  return result
}

function getActiveValue(state) {
  const generation = getHighestActiveGeneration(state)
  return generation === null ? null : { generation, ...state.values.get(generation) }
}

function pathsEqual(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function ancestorPathIds(path) {
  return path.slice(0, -1).map((_, index) => JSON.stringify(path.slice(0, index + 1)))
}

function materializeLegacyFields(activeFields) {
  const output = {}
  const orderedFields = activeFields.sort((left, right) => (
    left.value.path.length - right.value.path.length
    || compareStableStrings(JSON.stringify(left.value.path), JSON.stringify(right.value.path))
  ))
  const activePathGenerations = new Map()
  const blockedPaths = []
  for (const active of orderedFields) {
    const pathId = active.pathId
    const path = active.value.path
    if (blockedPaths.some(path => (
      path.length < active.value.path.length
      && path.every((segment, index) => segment === active.value.path[index])
    ))) continue
    const expectedAncestors = ancestorPathIds(path).map(id => (
      activePathGenerations.get(id)
    ))
    if (
      expectedAncestors.some(generation => generation === undefined)
      || !pathsEqual(active.value.ancestors, expectedAncestors)
    ) {
      blockedPaths.push(path)
      continue
    }
    let parent = output
    let validParent = true
    for (const segment of path.slice(0, -1)) {
      if (!isPlainRecord(parent[segment])) {
        validParent = false
        break
      }
      parent = parent[segment]
    }
    if (!validParent) {
      blockedPaths.push(path)
      continue
    }
    const field = path.at(-1)
    if (active.value.kind === 'object') {
      setObjectValue(parent, field, {})
    } else {
      setObjectValue(parent, field, cloneValue(active.value.value))
      blockedPaths.push(path)
    }
    activePathGenerations.set(pathId, active.generation)
  }
  return output
}

function materializeCompactFields(activeFields) {
  const output = {}
  const childrenByParent = new Map()
  for (const active of activeFields) {
    const parentPathId = active.value.parentPathId
    let children = childrenByParent.get(parentPathId)
    if (!children) {
      children = []
      childrenByParent.set(parentPathId, children)
    }
    children.push(active)
  }
  for (const children of childrenByParent.values()) {
    children.sort((left, right) => (
      compareStableStrings(left.value.segment, right.value.segment)
      || compareStableStrings(left.pathId, right.pathId)
    ))
  }

  const pending = [{ pathId: null, generation: null, output }]
  const visited = new Set()
  while (pending.length) {
    const parent = pending.pop()
    const children = childrenByParent.get(parent.pathId) || []
    const nextParents = []
    for (const active of children) {
      if (
        visited.has(active.pathId)
        || active.value.parentGeneration !== parent.generation
      ) continue
      visited.add(active.pathId)
      if (active.value.kind === 'object') {
        const childOutput = {}
        setObjectValue(parent.output, active.value.segment, childOutput)
        nextParents.push({
          pathId: active.pathId,
          generation: active.generation,
          output: childOutput,
        })
      } else {
        const decoded = decodeStoredValue(active.value)
        if (!decoded.valid) continue
        setObjectValue(
          parent.output,
          active.value.segment,
          decoded.value,
        )
      }
    }
    for (let index = nextParents.length - 1; index >= 0; index -= 1) {
      pending.push(nextParents[index])
    }
  }
  return output
}

function materializeRecord(record, recordGeneration) {
  const activeFields = []
  for (const [pathId, state] of (
    record.fields.get(recordGeneration) || new Map()
  )) {
    const active = getActiveValue(state)
    if (active) activeFields.push({ pathId, ...active })
  }
  const compactFields = activeFields.filter(active => active.value.pathFormat === 2)
  // A normal writer migrates every field of a record in one transaction. If a
  // transient pre-compact v2 state is encountered, keep its legacy materializer
  // solely as a read/migration fallback; current records always use compact IDs.
  const output = compactFields.length > 0
    ? materializeCompactFields(compactFields)
    : materializeLegacyFields(activeFields)
  if (record.domain === 'groups') {
    output.memberUids = [...(
      record.members.get(recordGeneration) || new Map()
    ).entries()]
      .filter(([, state]) => getHighestActiveGeneration(state) !== null)
      .map(([memberUid]) => memberUid)
      .sort(compareStableStrings)
  }
  return output
}

export function hasCrossNodeRecordStateV2(doc) {
  return Object.values(getMaps(doc)).some(yMap => yMap.size > 0)
}

export function readCrossNodeRecordStateV2(doc) {
  const { records } = collectRawIndex(doc)
  const state = Object.fromEntries(DOMAINS.map(domain => [domain, {}]))
  for (const record of records.values()) {
    const recordGeneration = getHighestActiveGeneration(record)
    if (recordGeneration === null) continue
    const materialized = materializeRecord(record, recordGeneration)
    // Empty groups are retained internally so concurrent member additions are
    // not lost, but they do not exist in the canonical simple-mind-map model.
    if (record.domain === 'groups' && materialized.memberUids.length === 0) continue
    state[record.domain][record.recordKey] = materialized
  }
  return state
}

function createRecordGeneration(index, record, generation) {
  const changed = setIfChanged(
    index.maps.recordEpochs,
    encodeRecordGenerationKey(record.domain, record.recordKey, generation),
    true,
  )
  record.generations.add(generation)
  return changed
}

function tombstoneGeneration(yMap, encodedKey, state, generation) {
  if (generation === null || state.tombstones.has(generation)) return false
  const changed = setIfChanged(yMap, encodedKey, true)
  state.tombstones.add(generation)
  return changed
}

function syncFieldPaths(index, record, recordGeneration, desired) {
  const current = ensureRecordGenerationCollection(record.fields, recordGeneration)
  let changed = false
  for (const [pathId, state] of current) {
    if (desired.has(pathId)) continue
    const generation = getHighestActiveGeneration(state)
    changed = tombstoneGeneration(
      index.maps.fieldTombstones,
      encodeFieldKey(record.domain, record.recordKey, recordGeneration, pathId, generation),
      state,
      generation,
    ) || changed
  }

  const chosenGenerations = new Map()
  for (const [pathId, desiredValue] of desired) {
    const state = ensurePathState(record, recordGeneration, pathId)
    let active = getActiveValue(state)
    const parentGeneration = desiredValue.parentPathId === null
      ? null
      : chosenGenerations.get(desiredValue.parentPathId)
    const typeChanged = Boolean(active && active.value.kind !== desiredValue.kind)
    const lineageChanged = Boolean(active && (
      active.value.pathFormat !== 2
      || active.value.parentPathId !== desiredValue.parentPathId
      || active.value.parentGeneration !== parentGeneration
      || active.value.segment !== desiredValue.segment
    ))
    if (typeChanged || lineageChanged) {
      changed = tombstoneGeneration(
        index.maps.fieldTombstones,
        encodeFieldKey(
          record.domain,
          record.recordKey,
          recordGeneration,
          pathId,
          active.generation,
        ),
        state,
        active.generation,
      ) || changed
      active = null
    }
    const generation = active?.generation ?? ((getHighestGeneration(state) ?? -1) + 1)
    const storedValue = {
      kind: desiredValue.kind,
      ...(desiredValue.kind === 'value' ? {
        encodedValue: desiredValue.encodedValue,
        valueEncoding: desiredValue.valueEncoding,
      } : {}),
      pathFormat: 2,
      parentPathId: desiredValue.parentPathId,
      parentGeneration,
      segment: desiredValue.segment,
    }
    const encodedKey = encodeFieldKey(
      record.domain,
      record.recordKey,
      recordGeneration,
      pathId,
      generation,
    )
    changed = setIfChanged(index.maps.fields, encodedKey, storedValue) || changed
    state.generations.add(generation)
    state.values.set(generation, { encodedKey, value: storedValue })
    chosenGenerations.set(pathId, generation)
  }
  return changed
}

function syncGroupMembers(index, record, recordGeneration, desired) {
  const current = ensureRecordGenerationCollection(record.members, recordGeneration)
  let changed = false
  for (const [memberUid, state] of current) {
    if (desired.has(memberUid)) continue
    const generation = getHighestActiveGeneration(state)
    changed = tombstoneGeneration(
      index.maps.memberTombstones,
      encodeMemberKey(record.recordKey, recordGeneration, memberUid, generation),
      state,
      generation,
    ) || changed
  }
  for (const memberUid of desired) {
    const state = ensureMemberState(record, recordGeneration, memberUid)
    if (getHighestActiveGeneration(state) !== null) continue
    const generation = (getHighestGeneration(state) ?? -1) + 1
    const encodedKey = encodeMemberKey(
      record.recordKey,
      recordGeneration,
      memberUid,
      generation,
    )
    changed = setIfChanged(index.maps.members, encodedKey, true) || changed
    state.generations.add(generation)
    state.values.set(generation, { encodedKey, value: true })
  }
  return changed
}

function prepareRecord(domain, desiredRecord) {
  // Validate and encode the complete semantic record before activating a new
  // generation. Yjs transactions do not roll back when their callback throws;
  // discovering an unsupported value after createRecordGeneration would leave
  // an observable empty record behind.
  return {
    desiredFields: flattenRecord(desiredRecord, domain),
    desiredMembers: domain === 'groups'
      ? new Set((desiredRecord?.memberUids || []).map(String))
      : null,
  }
}

function prepareStateRecords(state) {
  return new Map(DOMAINS.map(domain => [
    domain,
    new Map(Object.entries(state[domain]).map(([recordKey, desiredRecord]) => [
      recordKey,
      { desiredRecord, ...prepareRecord(domain, desiredRecord) },
    ])),
  ]))
}

function syncRecord(index, domain, recordKey, preparedRecord) {
  const { desiredFields, desiredMembers } = preparedRecord
  const record = ensureRecord(index.records, domain, recordKey)
  let recordGeneration = getHighestActiveGeneration(record)
  let changed = false
  if (recordGeneration === null) {
    recordGeneration = (getHighestGeneration(record) ?? -1) + 1
    changed = createRecordGeneration(index, record, recordGeneration) || changed
  }
  changed = syncFieldPaths(index, record, recordGeneration, desiredFields) || changed
  if (domain === 'groups') {
    changed = syncGroupMembers(index, record, recordGeneration, desiredMembers) || changed
  }
  return changed
}

function tombstoneRecord(index, domain, recordKey) {
  const record = index.records.get(encodeRecordId(domain, recordKey))
  const generation = getHighestActiveGeneration(record)
  if (generation === null) return false
  return tombstoneGeneration(
    index.maps.recordTombstones,
    encodeRecordGenerationKey(domain, recordKey, generation),
    record,
    generation,
  )
}

/** Replace active semantic state while retaining generation tombstones. */
export function replaceCrossNodeRecordStateV2(doc, state = {}) {
  const desired = normalizeState(state)
  // Preflight the whole replacement before the first Y.Map write. A thrown
  // getter or unsupported value in a later record must not tombstone valid
  // current records or leave earlier desired records half-applied.
  const preparedRecords = prepareStateRecords(desired)
  const index = collectRawIndex(doc)
  let changed = false
  for (const domain of DOMAINS) {
    const desiredRecords = desired[domain]
    for (const record of index.records.values()) {
      if (
        record.domain === domain
        && getHighestActiveGeneration(record) !== null
        && !Object.prototype.hasOwnProperty.call(desiredRecords, record.recordKey)
      ) changed = tombstoneRecord(index, domain, record.recordKey) || changed
    }
    for (const [recordKey, preparedRecord] of preparedRecords.get(domain)) {
      changed = syncRecord(index, domain, recordKey, preparedRecord) || changed
    }
  }
  return changed
}

/** Apply a semantic delta without rewriting untouched paths or members. */
export function applyCrossNodeRecordDeltaV2(doc, delta) {
  if (!delta) return false
  const preparedDelta = new Map(DOMAINS.map(domain => {
    const domainDelta = delta[domain]
    return [domain, {
      deletedKeys: [...(domainDelta?.deletedKeys || [])].map(String),
      upserts: new Map(Object.entries(domainDelta?.upserts || {}).map(([
        recordKey,
        desiredRecord,
      ]) => [recordKey, { desiredRecord, ...prepareRecord(domain, desiredRecord) }])),
    }]
  }))
  const index = collectRawIndex(doc)
  let changed = false
  for (const domain of DOMAINS) {
    const domainDelta = preparedDelta.get(domain)
    for (const recordKey of domainDelta.deletedKeys) {
      changed = tombstoneRecord(index, domain, recordKey) || changed
    }
    for (const [recordKey, preparedRecord] of domainDelta.upserts) {
      changed = syncRecord(index, domain, recordKey, preparedRecord) || changed
    }
  }
  return changed
}
