export const SMM_FORMAT = 'ruoyi-mindmap' as const
export const SMM_SCHEMA_VERSION = 2 as const
export const SMM_HASH_PREFIX = 'mmf2:sha256:' as const
export const DEFAULT_RESULT_TYPES = ['artifact'] as const
export const DISCUSSION_INTENT = 'discuss' as const
export const MESSAGE_TARGET = 'message' as const
export const MAX_AGENT_MESSAGE_LENGTH = 20_000
export const MAX_AGENT_MESSAGE_BYTES = 64 * 1024
export const MAX_AGENT_MESSAGE_TITLE_LENGTH = 200

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }
export type AgentResultType = 'artifact' | 'message'
export type AgentTarget = 'file' | 'proposal' | 'message'

export interface AgentCapabilityManifest {
  intents: readonly string[]
  /** Omit for adapters created before discussion support; they remain artifact-only. */
  resultTypes?: readonly AgentResultType[]
  [key: string]: unknown
}

export interface AgentRequestContract {
  intent: string
  target: AgentTarget
  resultType: AgentResultType
}

export interface AgentMessageCompletion {
  completionState: 'message_completed'
  title: string | null
  content: string
  contentType: 'text/plain'
}

export interface MindmapNode {
  data: { uid: string; text: string; expand?: boolean; [key: string]: JsonValue | undefined }
  children: MindmapNode[]
}

export interface MindmapDocument {
  root: MindmapNode
  layout: string
  theme: Record<string, JsonValue>
  view: Record<string, JsonValue> | null
  documentData: Record<string, JsonValue>
}

export interface SmmArtifact {
  format: typeof SMM_FORMAT
  formatSchemaVersion: typeof SMM_SCHEMA_VERSION
  manifest: {
    artifactId: string
    title: string
    sourceType: 'external_agent'
    createdAt: string
    generator: { agentKey: string; adapterVersion: string; promptVersion: string }
    validation: { status: 'passed' | 'draft'; validatorVersion: string }
    provenance: 'external_unverified'
    documentHash: string
  }
  document: MindmapDocument
}

const allowedLayouts = new Set([
  'mindMap', 'logicalStructure', 'organizationStructure', 'catalogOrganization',
  'timeline', 'timeline2', 'verticalTimeline', 'verticalTimeline2', 'verticalTimeline3',
  'fishbone', 'fishbone2', 'rightFishbone', 'rightFishbone2', 'logicalStructureLeft',
])
const supportedResultTypes = new Set<AgentResultType>(['artifact', 'message'])
const supportedTargets = new Set<AgentTarget>(['file', 'proposal', 'message'])
const unsafeMessageControlPattern = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/u

function nonEmptyUniqueStrings(value: unknown, fieldName: string): string[] {
  if (!Array.isArray(value) || value.length === 0 || value.some(item => typeof item !== 'string' || !item.trim())) {
    throw new Error(`manifest.${fieldName} must be a non-empty string array`)
  }
  const normalized = value.map(item => (item as string).trim())
  if (new Set(normalized).size !== normalized.length) {
    throw new Error(`manifest.${fieldName} cannot contain duplicates`)
  }
  return normalized
}

export function resolveResultTypes(manifest: Readonly<Record<string, unknown>>): AgentResultType[] {
  if (manifest === null || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new Error('manifest must be an object')
  }
  const values = nonEmptyUniqueStrings(manifest.resultTypes ?? DEFAULT_RESULT_TYPES, 'resultTypes')
  if (values.some(value => !supportedResultTypes.has(value as AgentResultType))) {
    throw new Error('manifest.resultTypes supports only artifact and message')
  }
  return values as AgentResultType[]
}

export function normalizeAgentManifest<T extends Readonly<Record<string, unknown>>>(
  manifest: T,
): T & { intents: string[]; resultTypes: AgentResultType[] } {
  if (manifest === null || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new Error('manifest must be an object')
  }
  const intents = nonEmptyUniqueStrings(manifest.intents, 'intents')
  const resultTypes = resolveResultTypes(manifest)
  if (intents.includes(DISCUSSION_INTENT) && !resultTypes.includes('message')) {
    throw new Error('manifest declaring discuss must also declare resultTypes message')
  }
  return { ...manifest, intents, resultTypes }
}

export function validateAgentRequest(
  intent: string,
  target: string,
  manifest?: Readonly<Record<string, unknown>>,
): AgentRequestContract {
  if (typeof intent !== 'string' || !intent.trim()) throw new Error('request.intent must be a non-empty string')
  if (!supportedTargets.has(target as AgentTarget)) throw new Error('request.target must be file, proposal, or message')
  const normalizedIntent = intent.trim()
  const normalizedTarget = target as AgentTarget
  let resultType: AgentResultType
  if (normalizedIntent === DISCUSSION_INTENT) {
    if (normalizedTarget !== MESSAGE_TARGET) throw new Error('discuss requests must target message')
    resultType = 'message'
  } else {
    if (normalizedTarget === MESSAGE_TARGET) throw new Error('only discuss requests may target message')
    resultType = 'artifact'
  }
  if (manifest !== undefined) {
    const capabilities = normalizeAgentManifest(manifest)
    if (!capabilities.intents.includes(normalizedIntent)) {
      throw new Error(`manifest does not support intent: ${normalizedIntent}`)
    }
    if (!capabilities.resultTypes.includes(resultType)) {
      throw new Error(`manifest does not support result type: ${resultType}`)
    }
  }
  return { intent: normalizedIntent, target: normalizedTarget, resultType }
}

export function agentMessageJsonSchema(): Record<string, JsonValue> {
  return {
    type: 'object',
    properties: {
      completionState: { type: 'string', enum: ['message_completed'] },
      title: { type: ['string', 'null'], maxLength: MAX_AGENT_MESSAGE_TITLE_LENGTH },
      content: { type: 'string', minLength: 1, maxLength: MAX_AGENT_MESSAGE_LENGTH },
      contentType: { type: 'string', enum: ['text/plain'] },
    },
    required: ['completionState', 'title', 'content', 'contentType'],
    additionalProperties: false,
  }
}

function unicodeLength(value: string): number {
  return Array.from(value).length
}

export function normalizeAgentMessageResult(value: unknown): AgentMessageCompletion {
  let payload: unknown = value
  if (typeof value === 'string') {
    try {
      payload = JSON.parse(value)
    } catch {
      payload = null
    }
  }
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('discussion result does not match the structured contract')
  }
  const record = payload as Record<string, unknown>
  const expectedKeys = ['completionState', 'title', 'content', 'contentType']
  if (
    Object.keys(record).length !== expectedKeys.length
    || expectedKeys.some(key => !Object.prototype.hasOwnProperty.call(record, key))
    || record.completionState !== 'message_completed'
    || record.contentType !== 'text/plain'
  ) {
    throw new Error('discussion result does not match the structured contract')
  }
  if (record.title !== null && typeof record.title !== 'string') {
    throw new Error('discussion title must be a string or null')
  }
  if (typeof record.content !== 'string') throw new Error('discussion content must be a string')
  const title = typeof record.title === 'string'
    ? (record.title.trim() ? record.title.trim().split(/\s+/u).join(' ') : null)
    : null
  const content = record.content.trim()
  if (
    (title !== null && (
      unicodeLength(title) > MAX_AGENT_MESSAGE_TITLE_LENGTH
      || unsafeMessageControlPattern.test(title)
    ))
    || !content
    || unicodeLength(content) > MAX_AGENT_MESSAGE_LENGTH
    || new TextEncoder().encode(content).byteLength > MAX_AGENT_MESSAGE_BYTES
    || unsafeMessageControlPattern.test(content)
  ) {
    throw new Error('discussion result contains unsafe or overlong content')
  }
  return {
    completionState: 'message_completed',
    title,
    content,
    contentType: 'text/plain',
  }
}

export function buildAgentMessageResult(content: string, title: string | null = null): AgentMessageCompletion {
  return normalizeAgentMessageResult({
    completionState: 'message_completed',
    title,
    content,
    contentType: 'text/plain',
  })
}

function randomId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function sorted(value: JsonValue): JsonValue {
  if (Array.isArray(value)) return value.map(sorted)
  if (value === null || typeof value !== 'object') return value
  return Object.keys(value).sort().reduce<Record<string, JsonValue>>((output, key) => {
    output[key] = sorted(value[key])
    return output
  }, {})
}

export function canonicalJson(value: JsonValue): string {
  return JSON.stringify(sorted(value))
}

export async function computeDocumentHash(document: MindmapDocument): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error('Web Crypto is required to compute an SMM v2 hash')
  const encoded = new TextEncoder().encode(canonicalJson(document as unknown as JsonValue))
  const digest = await globalThis.crypto.subtle.digest('SHA-256', encoded)
  const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  return `${SMM_HASH_PREFIX}${hex}`
}

export class MindmapBuilder {
  readonly document: MindmapDocument

  constructor(title: string, layout = 'logicalStructure') {
    if (!title.trim()) throw new Error('title is required')
    if (!allowedLayouts.has(layout)) throw new Error('unsupported layout')
    this.document = {
      root: { data: { uid: randomId(), text: title.trim(), expand: true }, children: [] },
      layout,
      theme: { template: 'default', config: {} },
      view: null,
      documentData: {},
    }
  }

  get rootUid(): string { return this.document.root.data.uid }

  addNodes(nodes: Array<{ parentUid: string; text: string; note?: string; hyperlink?: string }>): string[] {
    if (nodes.length < 1 || nodes.length > 200) throw new Error('addNodes accepts 1 to 200 nodes')
    const candidate = structuredClone(this.document)
    const index = new Map<string, MindmapNode>()
    const pending = [candidate.root]
    while (pending.length) {
      const node = pending.pop()!
      index.set(node.data.uid, node)
      pending.push(...node.children)
    }
    const created = nodes.map(input => {
      const parent = index.get(input.parentUid)
      if (!parent) throw new Error(`parent node does not exist: ${input.parentUid}`)
      if (!input.text.trim()) throw new Error('node text is required')
      const child: MindmapNode = {
        data: { uid: randomId(), text: input.text.trim(), expand: true },
        children: [],
      }
      if (input.note !== undefined) child.data.note = input.note
      if (input.hyperlink !== undefined) child.data.hyperlink = input.hyperlink
      parent.children.push(child)
      index.set(child.data.uid, child)
      return child.data.uid
    })
    Object.assign(this.document, candidate)
    return created
  }

  async complete(options: {
    title: string
    agentKey: string
    adapterVersion: string
    promptVersion: string
    artifactId?: string
    validationStatus?: 'passed' | 'draft'
  }): Promise<SmmArtifact> {
    const artifact: SmmArtifact = {
      format: SMM_FORMAT,
      formatSchemaVersion: SMM_SCHEMA_VERSION,
      manifest: {
        artifactId: options.artifactId ?? randomId(),
        title: options.title.trim().slice(0, 200),
        sourceType: 'external_agent',
        createdAt: new Date().toISOString(),
        generator: {
          agentKey: options.agentKey,
          adapterVersion: options.adapterVersion,
          promptVersion: options.promptVersion,
        },
        validation: {
          status: options.validationStatus ?? 'passed',
          validatorVersion: 'mindmap-agent-kit-ts-1',
        },
        provenance: 'external_unverified',
        documentHash: await computeDocumentHash(this.document),
      },
      document: structuredClone(this.document),
    }
    await validateArtifact(artifact, false)
    return artifact
  }
}

export async function validateArtifact(artifact: SmmArtifact, requirePassed = true): Promise<void> {
  if (artifact.format !== SMM_FORMAT || artifact.formatSchemaVersion !== SMM_SCHEMA_VERSION) {
    throw new Error('artifact must use ruoyi-mindmap SMM v2')
  }
  if (requirePassed && artifact.manifest.validation.status !== 'passed') throw new Error('draft artifact cannot be applied')
  if (!allowedLayouts.has(artifact.document.layout)) throw new Error('unsupported layout')
  const seen = new Set<string>()
  const pending: Array<[MindmapNode, number]> = [[artifact.document.root, 1]]
  let count = 0
  while (pending.length) {
    const [node, depth] = pending.pop()!
    count += 1
    if (count > 2000 || depth > 32) throw new Error('document exceeds SMM v2 structural limits')
    if (!node.data.uid || !node.data.text.trim() || seen.has(node.data.uid)) throw new Error('node uid/text must be non-empty and uid must be unique')
    seen.add(node.data.uid)
    if (Object.keys(node.data).some(key => key.toLowerCase().startsWith('on'))) throw new Error('node contains a forbidden event field')
    if (node.data.hyperlink !== undefined) {
      const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(String(node.data.hyperlink))?.[1]?.toLowerCase()
      if (!scheme || !['http', 'https', 'mailto'].includes(scheme)) throw new Error('node contains an unsafe hyperlink')
    }
    pending.push(...node.children.map(child => [child, depth + 1] as [MindmapNode, number]))
  }
  if (artifact.manifest.documentHash !== await computeDocumentHash(artifact.document)) {
    throw new Error('documentHash does not match document content')
  }
  if (new TextEncoder().encode(JSON.stringify(artifact)).byteLength > 2_000_000) {
    throw new Error('artifact cannot exceed 2000000 bytes')
  }
}
