// Execute the real presentation computeds without mounting authenticated app
// services. Shared by regression tests and the browser reproduction fixture.
export function createNoticeHarness(source, { ref, computed }) {
  const s = {
    job: ref({ id: 'notice-job', status: 'running' }), running: ref(true),
    livePreviewActive: ref(true), livePreviewRendering: ref(false),
    livePreviewFramesPending: ref(true), latestPreviewVersion: ref(12), livePreviewRenderedVersion: ref(11),
    livePreviewRenderedNodeCount: ref(49), livePreviewTargetNodeCount: ref(50),
    livePreviewChangeSummary: ref({ added: 5, updated: 3, moved: 1, deleted: 0 }),
    livePreviewAutoAccepting: ref(false), livePreviewAutoAcceptFailedJobId: ref(''),
    applying: ref(false), cancelling: ref(false), livePreviewReverting: ref(false),
    realtimeConnectionState: ref('connected'), highImpactReviewRequired: ref(false),
    livePreviewPaused: ref(false), livePreviewNoticeVisible: ref(true), livePreviewPlaybackAvailable: ref(true),
    currentResultState: ref({ description: '云端写入已确认，画布同步单独确认。' }),
  }
  s.livePreviewPausedVisible = computed(() => s.livePreviewPaused.value && s.livePreviewPlaybackAvailable.value)
  const start = source.indexOf('const livePreviewCatchingUp = computed(')
  const end = source.indexOf('const selectedTurn = computed(', start)
  if (start < 0 || end < start) throw new Error('Preview notice declarations not found')
  const api = new Function('scope', 'computed', `with (scope) { ${source.slice(start, end)}
    return { livePreviewCatchingUp, livePreviewNoticeTitle, livePreviewNoticeDescription }; }`)(s, computed)
  return { ...s, ...api }
}

export function noticeTemplate(source) {
  const marker = source.indexOf('v-if="livePreviewNoticeVisible"')
  const start = source.lastIndexOf('<div', marker)
  const end = source.indexOf('<p\n            v-if="livePreviewAccessibleAnnouncement"', marker)
  if (start < 0 || end < start) throw new Error('Preview notice template not found')
  return source.slice(start, end).trim()
}

export function noticeStyles(source) {
  const start = source.indexOf('.liveDraftNotice {')
  const end = source.indexOf('.livePreviewRecovery {', start)
  const pulse = source.indexOf('@keyframes aiPulse {')
  return source.slice(start, end) + source.slice(pulse, source.indexOf('@media', pulse))
}
