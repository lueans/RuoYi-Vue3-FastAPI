import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertMindmapAiArtifactDownloadResponse,
  formatMindmapAiError,
  formatMindmapAiJobError,
  isMindmapAiAbortError,
  resolveMindmapAiErrorCode,
} from '../mindmap-ai-errors.js'

test('取消识别统一支持 fetch 与 Axios，不把网络或业务失败当作取消', () => {
  for (const error of [new DOMException('cancelled', 'AbortError'), { name: 'CanceledError' }, { code: 'ERR_CANCELED' }]) {
    assert.equal(isMindmapAiAbortError(error), true)
  }
  for (const error of [null, undefined, new Error('offline'), { errorCode: 'AI_TASK_CANCELLED' }, { code: 'ERR_NETWORK' }]) {
    assert.equal(isMindmapAiAbortError(error), false)
  }
})

test('AI 业务错误从请求 data 与任务字段提取并映射为可操作文案', () => {
  const requestError = new Error('/private/provider/raw-error')
  requestError.data = { errorCode: 'AI_PROPOSAL_STALE' }
  assert.equal(resolveMindmapAiErrorCode(requestError), 'AI_PROPOSAL_STALE')
  assert.equal(
    formatMindmapAiError(requestError),
    '脑图内容已变化，请基于最新版本重新生成提案',
  )
  assert.equal(
    formatMindmapAiError({
      errorCode: 'AI_SANDBOX_VIOLATION',
      errorMessage: '包含不应展示的供应商原文',
    }),
    'Agent 尝试执行未授权操作，任务已被安全终止',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_TIMEOUT', errorMessage: 'provider stderr' }),
    'AI 任务运行超时，请缩小范围或稍后重试',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_SESSION_UNAVAILABLE' }),
    '原 AI 会话不存在或已结束，无法保留该会话记录继续重试',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_INPUT_INVALID' }),
    '输入内容或授权范围无效，请检查后重试',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_MODEL_CONFIG_INVALID' }),
    '所选模型配置无效，请到 AI 模型管理检查提供商、模型编码和 Base URL',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_PROPOSAL_INTEGRITY_INVALID' }),
    'AI 提案与生成结果不一致，已阻止应用；请保留错误详情并重新生成',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_PROPOSAL_FORMAT_OBSOLETE' }),
    '该 AI 提案来自旧版操作协议，无法安全升级时请重新生成',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_FOLLOWUP_BASE_INVALID' }),
    '继续调整的内容基线无效，请回到原脑图并刷新后重试',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_FOLLOWUP_STATE_CHANGED' }),
    '继续调整前任务状态已变化，请刷新后重试',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_FOLLOWUP_REVIEW_REQUIRED' }),
    '当前结果需要先确认或不采纳，再继续下一轮',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_DOCUMENT_CONFLICT' }),
    '脑图内容已被协作者修改，AI 直写已停止；请刷新后重试',
  )
  assert.equal(
    formatMindmapAiError({ errorCode: 'AI_APPLY_CONFLICT' }),
    '确认期间仍有新的协作修改，覆盖未完成；请再次点击覆盖当前脑图',
  )
})

test('未知本地错误保留明确消息，无消息时使用调用方兜底', () => {
  assert.equal(formatMindmapAiError(new Error('文件解析失败'), '兜底'), '文件解析失败')
  assert.equal(
    formatMindmapAiError({ errorMessage: '/private/provider/raw stderr' }, '兜底'),
    '兜底',
  )
  assert.equal(formatMindmapAiError(null, '兜底'), '兜底')
})

test('受信任任务状态优先展示精确原因并附错误码和安全行动建议', () => {
  assert.equal(
    formatMindmapAiJobError({
      id: 'job-limit',
      status: 'failed',
      errorCode: 'AI_BUDGET_EXCEEDED',
      errorMessage: '生成结果包含 102 个节点，超过上限 100',
    }),
    '生成结果包含 102 个节点，超过上限 100（错误码：AI_BUDGET_EXCEEDED）；任务已达到预算、用量或时长上限，请缩小范围后重试',
  )
  assert.equal(
    formatMindmapAiJobError({ errorCode: 'AI_TIMEOUT' }),
    'AI 任务运行超时，请缩小范围或稍后重试（错误码：AI_TIMEOUT）',
  )
  assert.equal(
    formatMindmapAiJobError({ errorCode: 'AI_DOCUMENT_CONFLICT' }),
    '脑图内容已被协作者修改，AI 直写已停止；请刷新后重试（错误码：AI_DOCUMENT_CONFLICT）',
  )
  assert.equal(
    formatMindmapAiError({
      errorCode: 'AI_OUTPUT_INVALID',
      errorMessage: '/private/provider/raw stderr',
    }),
    'AI 输出未通过安全与结构校验；可保留错误详情后重试任务，或切换 Agent 再试',
    'ordinary exceptions must not gain trusted-detail precedence',
  )
})

test('blob 下载中的业务错误信封不会被当成 SMM artifact', async () => {
  const errorBlob = new Blob([JSON.stringify({
    code: 500,
    success: false,
    msg: '结果已过期',
    data: { errorCode: 'AI_ARTIFACT_EXPIRED' },
  })], { type: 'application/json' })

  await assert.rejects(
    () => assertMindmapAiArtifactDownloadResponse(errorBlob),
    error => (
      error?.message === '结果已过期'
      && error?.code === 'AI_ARTIFACT_EXPIRED'
      && error?.data?.errorCode === 'AI_ARTIFACT_EXPIRED'
    ),
  )

  const artifactBlob = new Blob([JSON.stringify({
    format: 'ruoyi-mindmap',
    formatSchemaVersion: 2,
  })], { type: 'application/json' })
  assert.equal(await assertMindmapAiArtifactDownloadResponse(artifactBlob), artifactBlob)
})
