import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMindmapAiConversationTurns,
  deriveMindmapAiSessionTitle,
  isMindmapAiMessageJob,
  normalizeMindmapAiSessionList,
  resolveMindmapAiContextAvailability,
  resolveMindmapAiSessionTitle,
  summarizeMindmapAiUsage,
} from '../mindmap-ai-conversation.js'

test('session titles are deterministic and legacy sessions recover from first prompt', () => {
  assert.equal(deriveMindmapAiSessionTitle('  第一行\n\t第二行\u0000  '), '第一行 第二行')
  assert.equal(deriveMindmapAiSessionTitle('🧠'.repeat(50)), '🧠'.repeat(36))
  assert.equal(resolveMindmapAiSessionTitle('服务端标题', []), '服务端标题')
  assert.equal(resolveMindmapAiSessionTitle(null, [{
    userMessage: { content: '  旧会话的第一个问题  ' },
  }]), '旧会话的第一个问题')
  assert.equal(resolveMindmapAiSessionTitle(null, []), '未命名对话')
})

test('discussion mode is restored from the authoritative job target or intent', () => {
  assert.equal(isMindmapAiMessageJob({ target: 'message', intent: 'create' }), true)
  assert.equal(isMindmapAiMessageJob({ target: 'proposal', intent: 'discuss' }), true)
  assert.equal(isMindmapAiMessageJob({ target: 'proposal', intent: 'create' }), false)
})

test('usage summary exposes only supported counters and cost fields', () => {
  assert.deepEqual(summarizeMindmapAiUsage({
    inputTokens: 12,
    outputTokens: 8,
    totalCostUsd: 0.0123,
    costEstimated: true,
    secret: 'must-not-render',
  }), {
    inputTokens: 12,
    outputTokens: 8,
    totalTokens: 20,
    totalCostUsd: 0.0123,
    costEstimated: true,
  })
  assert.equal(summarizeMindmapAiUsage({ secret: 'drop' }), null)
  assert.equal(JSON.stringify(summarizeMindmapAiUsage({ token: 'secret' })), 'null')
})

test('context availability requires exactly one selected node for a branch', () => {
  assert.deepEqual(resolveMindmapAiContextAvailability({ selectedCount: 0 }), {
    document: true,
    branch: false,
    selectedNodes: false,
    newDocument: true,
    file: true,
  })
  assert.equal(resolveMindmapAiContextAvailability({ selectedCount: 1 }).branch, true)
  assert.equal(resolveMindmapAiContextAvailability({ selectedCount: 2 }).branch, false)
})

test('session list drops malformed and duplicate records', () => {
  assert.deepEqual(normalizeMindmapAiSessionList({
    total: 8,
    items: [
      { sessionId: 's-1', title: ' 会话 ', turnCount: 2, currentJob: { id: 'j-1' } },
      { sessionId: 's-1', title: '重复', currentJob: { id: 'j-2' } },
      { sessionId: 's-2', currentJob: null },
    ],
  }), {
    total: 8,
    items: [{
      sessionId: 's-1',
      title: '会话',
      status: '',
      currentAgentKey: '',
      turnCount: 2,
      updateTime: '',
      expiresTime: '',
      currentJob: { id: 'j-1' },
    }],
  })
})

test('conversation turns merge the live job, prompt and per-turn audit events', () => {
  const turns = buildMindmapAiConversationTurns({
    sessionTurns: [{
      job: { id: 'j-1', turnIndex: 1, status: 'completed_message' },
      assistantMessage: { content: '回答', createdTime: '2026-09-15T00:00:02Z' },
    }],
    currentJob: { id: 'j-1', turnIndex: 1, usage: { totalTokens: 22 } },
    events: [
      { jobId: 'j-1', eventType: 'user_prompt', payload: { message: '问题' }, createdTime: '2026-09-15T00:00:00Z' },
      { jobId: 'j-1', eventType: 'agent_started', payload: {}, createdTime: '2026-09-15T00:00:01Z' },
    ],
  })
  assert.equal(turns.length, 1)
  assert.equal(turns[0].userMessage.content, '问题')
  assert.equal(turns[0].assistantMessage.content, '回答')
  assert.equal(turns[0].events.length, 1)
  assert.deepEqual(turns[0].usage, { totalTokens: 22 })
})
