import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { ref } from 'vue'
import { validateMindmapAiAttachments } from '../mindmap-ai-attachments.js'
import { buildMindmapAiAttachmentMetadata } from '../mindmap-ai-attachment-records.js'

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const nodes = babelParse(script, { sourceType: 'module' }).program.body

// Supply the real production attachment state/helpers to focused SFC harnesses.
// Empty attachments retain each older test's original non-attachment scenario.
export function installComposerAttachmentHarness(scope) {
  scope.authExpired ??= ref(false)
  scope.composerAttachments ??= ref([])
  scope.attachmentNotice ??= ref('')
  scope.attachmentReading ??= ref(false)
  scope.attachmentReadGeneration ??= 0
  scope.privateAttachmentRequests ??= new Map()
  scope.pendingFollowupContext ??= ref(null)
  scope.pendingFollowupAttachments ??= ref([])
  scope.cloneRuntimeValue ??= value => value == null ? value : JSON.parse(JSON.stringify(value))
  scope.validateMindmapAiAttachments ??= validateMindmapAiAttachments
  scope.buildMindmapAiAttachmentMetadata ??= buildMindmapAiAttachmentMetadata
  const names = ['captureComposerAttachments', 'consumeComposerAttachments', 'clearComposerAttachments', 'replayableRequestPayload']
  const functions = nodes.filter(node => names.includes(node.id?.name))
  const api = new Function('scope', `with (scope) {
    ${functions.map(node => script.slice(node.start, node.end)).join('\n')}
    return { ${names.join(', ')} };
  }`)(scope)
  for (const name of names) scope[name] ??= api[name]
  return scope
}
