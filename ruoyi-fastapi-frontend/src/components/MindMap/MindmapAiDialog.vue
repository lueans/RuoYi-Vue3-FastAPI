<template>
  <el-drawer
    v-model="visible"
    class="mindmapAiDrawer"
    direction="ltr"
    size="500px"
    :modal="false"
    modal-penetrable
    modal-class="mindmapAiDrawerOverlay"
    :z-index="4000"
    :lock-scroll="false"
    :with-header="false"
    append-to-body
    :close-on-click-modal="false"
    @closed="onDialogClosed"
  >
    <input
      ref="sourceFileInputRef"
      class="aiSourceFileInput"
      type="file"
      accept=".xmind,.smm,.json,.md,.txt"
      @change="onSourceFileChange"
    />
    <header class="aiPanelHeader">
      <el-popover
        v-model:visible="sessionMenuVisible"
        placement="bottom-start"
        :width="332"
        trigger="click"
        popper-class="mindmapAiSessionPopper"
        :disabled="running || actionBusy"
        @show="loadRecentSessions"
      >
        <template #reference>
          <button
            type="button"
            class="newConversationButton"
            :disabled="running || actionBusy"
            aria-haspopup="menu"
            :aria-expanded="sessionMenuVisible"
          >
            <span>{{ currentSessionTitle }}</span>
            <el-icon class="headerChevron" aria-hidden="true"><ArrowDown /></el-icon>
          </button>
        </template>
        <div class="sessionMenu" role="menu" aria-label="AI 对话历史">
          <button type="button" class="sessionNewAction" role="menuitem" @click="startNewJob">
            <el-icon aria-hidden="true"><Plus /></el-icon>
            <span><strong>新建对话</strong><small>开始一个独立的 AI 任务</small></span>
          </button>
          <div class="sessionMenuHeading">
            <span>最近对话</span>
            <button
              v-if="sessionListError"
              type="button"
              :disabled="sessionListLoading"
              @click="loadRecentSessions"
            >重试</button>
          </div>
          <div v-if="sessionListLoading" class="sessionMenuState">正在加载最近对话…</div>
          <div v-else-if="sessionListError" class="sessionMenuState is-error">{{ sessionListError }}</div>
          <div v-else-if="!recentSessions.length" class="sessionMenuState">还没有历史对话</div>
          <div v-else class="sessionList">
            <button
              v-for="session in recentSessions"
              :key="session.sessionId"
              type="button"
              role="menuitem"
              :class="{ 'is-current': session.sessionId === job?.sessionId }"
              :disabled="Boolean(sessionUnavailableReason(session))"
              :title="sessionUnavailableReason(session) || session.title"
              @click="switchToSession(session)"
            >
              <span class="sessionListCopy">
                <strong>{{ session.title }}</strong>
                <small>{{ session.turnCount }} 轮 · {{ sessionStatusLabel(session) }}</small>
              </span>
              <time v-if="session.updateTime" :datetime="session.updateTime">{{ formatSessionTime(session.updateTime) }}</time>
            </button>
          </div>
        </div>
      </el-popover>
      <div class="aiPanelHeaderActions">
        <el-button
          v-if="!messageModeActive && (draftDocument?.root || running)"
          class="mobilePreviewToggle"
          text
          aria-controls="mindmap-ai-realtime-preview"
          :aria-label="mobilePreviewVisible ? '返回 AI 对话' : '查看实时脑图'"
          :aria-pressed="mobilePreviewVisible"
          @click="mobilePreviewVisible = !mobilePreviewVisible"
        >{{ mobilePreviewVisible ? '返回对话' : '实时脑图' }}</el-button>
        <span
          class="connectionBadge"
          :class="`is-${realtimeConnectionState}`"
          role="status"
          aria-live="polite"
        ><i aria-hidden="true"></i>{{ connectionStateLabel }}</span>
        <el-tooltip content="任务与 Agent 设置" placement="bottom" popper-class="mindmapAiTooltipPopper">
          <el-button
            circle
            text
            aria-label="任务与 Agent 设置"
            :class="{ 'is-active': showAdvancedSettings }"
            @click="showAdvancedSettings = !showAdvancedSettings"
          ><el-icon><Setting /></el-icon></el-button>
        </el-tooltip>
        <el-tooltip content="关闭 AI 面板" placement="bottom" popper-class="mindmapAiTooltipPopper">
          <el-button circle text aria-label="关闭 AI 面板" @click="visible = false">
            <el-icon><Close /></el-icon>
          </el-button>
        </el-tooltip>
      </div>
    </header>
    <div class="aiDialogBody" v-loading="loadingAgents || restoringJob">
      <aside
        v-if="job || agentEvents.length"
        class="activitySidebar"
        aria-label="AI 会话与安全审计记录"
        :aria-busy="timelineLoading || restoringJob"
      >
        <div class="activityHeader">
          <div>
            <strong>会话记录</strong>
            <small>{{ conversationTurns.length }} 轮对话 · 生成过程可展开</small>
          </div>
          <div class="activityHeaderActions">
            <el-button
              v-if="job?.sessionId"
              link
              type="danger"
              :loading="deletingSession"
              :disabled="actionBusy"
              @click="deleteSessionRecord"
            >删除记录</el-button>
          </div>
        </div>
        <el-skeleton v-if="timelineLoading" :rows="5" animated />
        <div v-else-if="timelineError" class="timelineLoadFailure">
          <el-alert
            :title="timelineError"
            type="warning"
            :closable="false"
            show-icon
          />
          <el-button
            size="small"
            type="warning"
            plain
            :loading="timelineLoading"
            :disabled="!job?.sessionId"
            @click="retrySessionTimeline"
          >重新加载会话记录</el-button>
        </div>
        <nav
          v-if="!messageModeActive && (artifactTurns.length || (job && !job.artifactId))"
          class="turnArtifacts"
          aria-label="历史轮次结果"
        >
          <strong>轮次结果</strong>
          <button
            v-for="turn in artifactTurns"
            :key="`turn:${turn.job.id}`"
            type="button"
            :class="{ 'is-selected': selectedTurnJobId === String(turn.job.id) }"
            :disabled="selectedArtifactLoading || actionBusy"
            @click="selectSessionTurn(turn)"
          >
            <span>第 {{ turn.job.turnIndex || 1 }} 轮</span>
            <small>{{ jobStatusLabels[turn.job.status] || turn.job.status }}</small>
          </button>
          <button
            v-if="job && !job.artifactId"
            type="button"
            :class="{ 'is-selected': selectedTurnJobId === String(job.id) }"
            :disabled="selectedArtifactLoading || actionBusy"
            @click="selectCurrentLiveTurn"
          >
            <span>第 {{ job.turnIndex || 1 }} 轮 · 实时</span>
            <small>{{ statusLabel }}</small>
          </button>
        </nav>
        <ol
          v-if="conversationTurns.length"
          ref="activityTimelineRef"
          class="activityTimeline conversationTimeline"
          aria-live="polite"
          aria-relevant="additions text"
        >
          <li
            v-for="turn in conversationTurns"
            :key="`conversation:${turn.job.id}`"
            class="conversationTurn"
          >
            <div v-if="turn.userMessage?.content" class="conversationMessage is-user">
              <div class="conversationMessageMeta">
                <strong>你</strong>
                <time :datetime="turn.userMessage.createdTime">{{ formatEventTime(turn.userMessage.createdTime) }}</time>
              </div>
              <p>{{ turn.userMessage.content }}</p>
            </div>
            <div class="conversationMessage is-assistant">
              <div class="conversationMessageMeta">
                <strong>AI · 第 {{ turn.job.turnIndex || 1 }} 轮</strong>
                <span>{{ displayJobStatusLabel(turn.job) }}</span>
              </div>
              <p>{{ assistantMessageText(turn) }}</p>
              <div v-if="turn.usage" class="usageSummary" aria-label="本轮 AI 用量">
                <span v-if="Number.isSafeInteger(turn.usage.totalTokens)">Token {{ turn.usage.totalTokens }}</span>
                <span v-if="Number.isFinite(turn.usage.totalCostUsd)">
                  {{ turn.usage.costEstimated ? '预估' : '费用' }} ${{ formatUsageCost(turn.usage.totalCostUsd) }}
                </span>
              </div>
              <details v-if="turn.events.length" class="turnAudit" :open="turn.job.id === job?.id && running">
                <summary>查看生成过程（{{ turn.events.length }}）</summary>
                <ol>
                  <li v-for="event in visibleTurnEvents(turn)" :key="event.key">
                    <span>{{ eventTypeLabel(event) }}</span>
                    <p>{{ eventDescription(event, turn.job) }}</p>
                    <time :datetime="event.createdTime">{{ formatEventTime(event.createdTime) }}</time>
                  </li>
                </ol>
                <small v-if="turn.events.length > 20">仅显示最近 20 条；完整记录仍保存在服务端会话中。</small>
              </details>
            </div>
          </li>
        </ol>
        <div v-else-if="!timelineLoading && job" class="activityEmpty">
          <strong>还没有会话记录</strong>
          <span>提交要求后，这里会显示每轮提示词与安全审计事件。</span>
        </div>
        <p class="privacyNotice">仅展示用户输入和经过清洗的运行审计，不展示模型隐藏思维链。</p>
      </aside>

      <main class="workspaceMain">
        <section class="controlPane">
          <el-alert
            v-if="agentError"
            :title="agentError"
            type="warning"
            show-icon
            :closable="false"
          />
          <el-alert
            v-if="pendingAttemptNotice"
            :title="pendingAttemptNotice"
            type="info"
            show-icon
            closable
            @close="pendingAttemptNotice = ''"
          />
          <div v-if="cloudMutationRecoveryError" class="restoreFailure">
            <el-alert
              :title="cloudMutationRecoveryError"
              type="warning"
              show-icon
              :closable="false"
            />
            <div class="restoreFailureActions">
              <el-button
                v-if="cloudMutationRetryable"
                size="small"
                type="warning"
                plain
                :loading="cloudMutationRecovering"
                @click="retryCloudMutationRecovery"
              >重新同步云端 AI 操作</el-button>
              <el-button
                v-if="cloudMutationHasPermanentFailure"
                size="small"
                type="danger"
                plain
                :disabled="cloudMutationRecovering"
                @click="discardPermanentCloudMutationRecovery"
              >已人工核对，清除记录</el-button>
            </div>
          </div>
          <div v-if="restoreError" class="restoreFailure">
            <el-alert
              :title="restoreError"
              type="warning"
              show-icon
              :closable="false"
            />
            <div class="restoreFailureActions">
              <el-button
                size="small"
                type="warning"
                plain
                :loading="restoringJob"
                @click="retryStoredJobRecovery"
              >重试恢复任务</el-button>
              <el-button size="small" :disabled="restoringJob" @click="discardStoredJobRecovery">
                放弃恢复并新建
              </el-button>
            </div>
          </div>

          <section v-if="!job && !agentEvents.length" class="aiWelcome">
            <div class="aiWelcomeMark" aria-hidden="true">
              <el-icon><MagicStick /></el-icon>
            </div>
            <h2>今天想做点什么？</h2>
            <div class="starterGrid">
              <button type="button" @click="usePromptStarter('research')">
                <el-icon><DataAnalysis /></el-icon>
                <span>调研一个主题并总结要点</span>
              </button>
              <button type="button" @click="usePromptStarter('plan')">
                <el-icon><List /></el-icon>
                <span>把一个项目拆解成执行计划</span>
              </button>
              <button type="button" @click="usePromptStarter('trends')">
                <el-icon><TrendCharts /></el-icon>
                <span>梳理某个领域的发展趋势</span>
              </button>
              <button type="button" @click="usePromptStarter('optimize')">
                <el-icon><MagicStick /></el-icon>
                <span>分析并优化我的思维导图</span>
              </button>
            </div>
          </section>

          <section v-show="showAdvancedSettings" class="advancedSettings">
            <div class="advancedSettingsHeader">
              <div>
                <strong>任务与 Agent 设置</strong>
                <small>Codex、Claude、自研 Agent 与后续适配器共用此入口</small>
              </div>
              <el-button text aria-label="收起设置" @click="showAdvancedSettings = false">
                <el-icon><Close /></el-icon>
              </el-button>
            </div>
          <el-form label-position="top" :model="form" @submit.prevent>
        <div class="formGrid">
          <el-form-item label="AI Agent">
            <el-select
              v-model="form.agentKey"
              placeholder="选择 Agent"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="agentSelectionLocked"
              @change="onAgentChange"
            >
              <el-option
                v-if="form.agentKey && !selectedAgent && !loadingAgents"
                :label="`${form.agentKey}（已不可用）`"
                :value="form.agentKey"
                disabled
              >
                <div class="agentOption is-unavailable">
                  <span>{{ form.agentKey }}</span>
                  <small>已不可用</small>
                </div>
              </el-option>
              <el-option
                v-for="agent in agents"
                :key="agent.agentKey"
                :label="agent.displayName"
                :value="agent.agentKey"
                :disabled="agent.status !== 'enabled' || !agentSupportsCurrentTask(agent)"
              >
                <div class="agentOption">
                  <span>{{ agent.displayName }}</span>
                  <small>{{ agentStatusText(agent) }}</small>
                </div>
              </el-option>
            </el-select>
            <div v-if="agentSelectionIssue" class="agentSelectionIssue" role="status">
              <el-icon aria-hidden="true"><WarningFilled /></el-icon>
              <span>{{ agentSelectionIssue }}</span>
            </div>
            <div
              v-if="selectedAgent"
              class="agentReadiness"
              :class="`is-${selectedAgentReadinessTone}`"
              role="status"
            >
              <i aria-hidden="true"></i>
              <div>
                <strong>{{ selectedAgentReadinessLabel }}</strong>
                <small>{{ selectedAgentReadinessDescription }}</small>
              </div>
            </div>
            <details v-if="selectedAgent" class="agentDisclosureDetails">
              <summary>连接与使用范围</summary>
              <div class="agentDisclosure">
                <span>{{ selectedAgent.sdkName }}<template v-if="selectedAgent.sdkVersion"> {{ selectedAgent.sdkVersion }}</template></span>
                <span v-if="selectedAgent.runtimeVersion">运行时 {{ selectedAgent.runtimeVersion }}</span>
                <span>{{ selectedAgent.authType || '平台认证' }}</span>
                <span>{{ selectedAgent.dataRegion || '区域由供应商连接决定' }}</span>
                <span>{{ selectedAgent.retentionPolicy || '结果按平台保留策略处理' }}</span>
                <span>{{ selectedAgent.networkAllowed ? '需要访问所选 AI 供应商' : 'Agent 本身无外部工具网络权限' }}</span>
                <span>单任务 {{ selectedAgent.timeoutSeconds }} 秒 / ${{ selectedAgent.maxBudgetUsd }}</span>
                <span>最多 {{ selectedAgent.maxNodes }} 节点、{{ selectedAgent.maxDepth }} 层</span>
              </div>
            </details>
          </el-form-item>

          <el-form-item v-if="form.agentKey === 'native_mindmap'" label="模型">
            <el-select
              v-model="form.modelId"
              placeholder="选择平台模型"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="agentSelectionLocked"
            >
              <el-option
                v-for="model in availableModels"
                :key="model.modelId"
                :label="model.modelName || model.modelCode"
                :value="model.modelId"
              />
            </el-select>
          </el-form-item>

          <el-form-item v-if="!discussionMode" label="任务">
            <el-select
              v-model="form.intent"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="taskConfigurationLocked"
              @change="onIntentChange"
            >
              <el-option
                v-for="item in intentOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="处理对象">
            <el-radio-group v-model="form.sourceMode" :disabled="taskConfigurationLocked">
              <el-radio value="current">当前脑图</el-radio>
              <el-radio value="new">新建脑图</el-radio>
              <el-radio value="file">本地文件</el-radio>
            </el-radio-group>
          </el-form-item>
        </div>

        <el-form-item v-if="form.sourceMode === 'file'" label="输入文件" required>
          <div class="sourceFileRow">
            <el-button :loading="parsingFile" :disabled="taskConfigurationLocked" @click="selectSourceFile">
              选择 XMind / SMM / JSON / Markdown / TXT
            </el-button>
            <span>{{ uploadedFileName || '尚未选择文件' }}</span>
          </div>
          <div class="fieldHint">文件只在浏览器解析；通过安全封装与校验后才作为 Agent 输入。</div>
        </el-form-item>

        <el-form-item v-if="form.sourceMode === 'current'" label="授权范围">
          <el-radio-group v-model="form.scopeType" :disabled="taskConfigurationLocked">
            <el-radio value="document">整份脑图</el-radio>
            <el-radio value="branch" :disabled="selectedNodeUids.length !== 1">当前分支</el-radio>
            <el-radio value="selectedNodes" :disabled="selectedNodeUids.length === 0">
              已选节点（{{ selectedNodeUids.length }}）
            </el-radio>
          </el-radio-group>
          <div class="fieldHint">局部范围只会向 Agent 暴露被授权的节点及其子树。</div>
        </el-form-item>

        <el-form-item label="你的要求" required>
          <el-input
            v-model="form.prompt"
            type="textarea"
            :rows="5"
            maxlength="20000"
            show-word-limit
            resize="vertical"
            :disabled="taskConfigurationLocked"
            placeholder="例如：为支付系统梳理核心流程与关键模块的脑图"
          />
        </el-form-item>

        <div class="formGrid compactGrid">
          <el-form-item label="输出语言">
            <el-select
              v-model="form.language"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="taskConfigurationLocked"
            >
              <el-option
                v-for="item in outputLanguageOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!discussionMode" label="目标布局">
            <el-select
              v-model="form.layout"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="taskConfigurationLocked || targetLayoutLocked"
            >
              <el-option
                v-for="item in aiLayoutOptions"
                :key="item.value"
                :label="item.name"
                :value="item.value"
              />
            </el-select>
            <div v-if="targetLayoutLocked" class="fieldHint">{{ targetLayoutHint }}</div>
            <div v-else class="fieldHint">生成过程和最终结果都会使用所选布局。</div>
          </el-form-item>
          <el-form-item label="内容密度">
            <el-select
              v-model="form.density"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="taskConfigurationLocked"
            >
              <el-option label="精简" value="concise" />
              <el-option label="标准" value="standard" />
              <el-option label="详细" value="detailed" />
            </el-select>
          </el-form-item>
          <el-form-item label="最多节点">
            <el-input-number
              v-model="form.maxNodes"
              :min="5"
              :max="maxNodesCap"
              :step="10"
              :disabled="taskConfigurationLocked"
            />
            <div class="fieldHint">编辑现有脑图时表示本次最多新增节点，不包含范围外历史节点。</div>
          </el-form-item>
          <el-form-item label="最大层级">
            <el-input-number
              v-model="form.maxDepth"
              :min="2"
              :max="maxDepthCap"
              :disabled="taskConfigurationLocked"
            />
          </el-form-item>
        </div>
          </el-form>
          </section>

          <section v-if="job" class="jobPanel" aria-live="polite">
        <div class="jobHeader">
          <div>
            <strong>{{ statusLabel }}</strong>
            <small>{{ job.agentKey }} · {{ job.id }}</small>
          </div>
          <span>{{ job.progress || 0 }}%</span>
        </div>
        <el-progress :percentage="job.progress || 0" :status="progressStatus" />
        <el-alert
          v-if="job.errorMessage || job.errorCode"
          :title="job.errorCode ? `${job.errorCode}：${jobErrorMessage}` : jobErrorMessage"
          type="error"
          show-icon
          :closable="false"
        />
        <div v-if="job.status === 'needs_input'" class="needsInputPanel">
          <strong>Agent 需要补充信息</strong>
          <ol v-if="needsInputQuestions.length">
            <li v-for="question in needsInputQuestions" :key="question.questionId">
              {{ question.prompt }}
            </li>
          </ol>
          <span v-else class="fieldHint">正在从安全审计记录恢复补充问题……</span>
          <span class="fieldHint">在下方填写答案后会创建新的任务轮次；当前轮次保持终态，不会被重新启动。</span>
        </div>
        <div v-if="retryAvailable" class="retryPanel">
          <strong>重试任务 · 创建独立的新轮次</strong>
          <el-input
            v-model="retryPrompt"
            type="textarea"
            :rows="3"
            maxlength="20000"
            show-word-limit
            placeholder="可编辑本轮要求；留空则复用原任务要求"
          />
          <div class="retryActions">
            <span class="fieldHint">
              可在上方切换 Agent 或模型。重试保留本会话的交互审计，但不会复用失败任务的供应商会话。
            </span>
            <el-button
              type="primary"
              plain
              :loading="retrying"
              :disabled="actionBusy"
              @click="retryJob"
            >重试任务</el-button>
          </div>
        </div>
        <div v-if="!messageModeActive && job.artifactId" class="resultSummary">
          <span>{{ isDraftArtifact(job.artifactId) ? '结果为安全草稿' : '已生成并通过 SMM v2 校验' }}</span>
          <span v-if="job.title">{{ job.title }}</span>
        </div>
        <div v-if="!messageModeActive && proposalError" class="proposalLoadFailure">
          <el-alert
            :title="proposalError"
            type="warning"
            show-icon
            :closable="false"
          />
          <el-button
            size="small"
            type="warning"
            plain
            :loading="proposalLoading"
            :disabled="actionBusy"
            @click="reloadProposal"
          >重新加载提案差异</el-button>
        </div>
        <div v-if="terminalHydrationState === 'error'" class="proposalLoadFailure">
          <el-alert
            :title="terminalHydrationError"
            type="warning"
            show-icon
            :closable="false"
          />
          <el-button
            size="small"
            type="warning"
            plain
            :loading="terminalHydrationState === 'loading'"
            :disabled="actionBusy"
            @click="retryTerminalHydration"
          >重新同步完成结果</el-button>
        </div>
        <details
          v-if="!messageModeActive && proposal"
          class="proposalPreview"
          :open="!proposalReviewFinalized"
          aria-label="AI 提案差异预览"
        >
          <summary v-if="proposalReviewFinalized" class="proposalReviewSummary">
            <span>
              <strong>{{ job.status === 'undone' ? '已撤销提案差异' : '已应用提案差异' }}</strong>
              <small>
                新增 {{ proposal.impact?.createdCount || 0 }} ·
                修改 {{ proposal.impact?.updatedCount || 0 }} ·
                移动 {{ proposal.impact?.movedCount || 0 }} ·
                删除 {{ proposal.impact?.deletedCount || 0 }}
              </small>
            </span>
            <el-icon aria-hidden="true"><ArrowDown /></el-icon>
          </summary>
          <div class="proposalReviewBody">
            <div class="diffCounts">
              <span>新增 {{ proposal.impact?.createdCount || 0 }}</span>
              <span>修改 {{ proposal.impact?.updatedCount || 0 }}</span>
              <span>移动 {{ proposal.impact?.movedCount || 0 }}</span>
              <span>删除 {{ proposal.impact?.deletedCount || 0 }}</span>
            </div>
            <el-alert
              v-if="proposal.impact?.highImpact"
              :title="proposal.impact.highImpactReasons?.join('；') || '这是高影响提案'"
              type="warning"
              show-icon
              :closable="false"
            />
            <ul v-if="proposal.impact?.changes?.length" class="diffList">
              <li
                v-for="(change, index) in proposal.impact.changes.slice(0, 12)"
                :key="`${change.type}:${change.nodeUid || index}`"
              >
                {{ changeTypeLabel(change.type) }} · {{ change.path || change.fromPath || '文档设置' }}
                <span v-if="change.subtreeSize">（子树 {{ change.subtreeSize }} 个节点）</span>
              </li>
            </ul>
            <div v-if="proposal.impact?.changes?.length > 12" class="fieldHint">
              另有 {{ proposal.impact.changes.length - 12 }} 项变化未展开。
            </div>
            <el-checkbox
              v-if="!proposalReviewFinalized"
              ref="proposalConfirmationRef"
              v-model="diffConfirmed"
              :disabled="actionBusy"
            >
              {{ sourceContext?.mindmapId
                ? '我已查看上述差异，确认用 AI 完整结果覆盖当前脑图（可撤销）'
                : '我已查看上述差异，确认将整项提案作为一次变更应用' }}
            </el-checkbox>
          </div>
        </details>
        <section
          v-if="followupAvailable"
          class="followupPanel"
        >
          <strong>{{ followupParentJob?.status === 'needs_input' ? '补充信息' : '继续调整' }} · 基于第 {{ followupParentJob?.turnIndex || 1 }} 轮</strong>
          <el-input
            v-model="followupPrompt"
            type="textarea"
            :rows="3"
            maxlength="20000"
            show-word-limit
            :placeholder="followupParentJob?.status === 'needs_input'
              ? '请按上方问题补充必要信息'
              : '例如：保留现有结构，再补充异常场景并减少重复节点'"
          />
          <div class="followupActions">
            <span class="fieldHint">
              {{ followupParentJob?.status === 'needs_input'
                ? '补充信息会继续当前任务，不能切换讨论/编辑模式。'
                : discussionMode
                  ? '下一轮将基于当前结果进行讨论，只返回回答，不修改脑图。'
                  : '下一轮将基于当前结果继续编辑脑图；可调整 Agent、模型与本轮要求。' }}
              切换 Agent 或讨论/编辑模式时，不迁移供应商隐藏上下文。
            </span>
            <el-button
              type="primary"
              plain
              :loading="continuing"
              :disabled="!followupPrompt.trim() || actionBusy"
              @click="continueJob"
            >继续生成</el-button>
          </div>
        </section>
          </section>
        </section>

        <Teleport to="body">
        <section
          v-if="visible && !messageModeActive && (draftDocument?.root || running)"
          id="mindmap-ai-realtime-preview"
          class="previewPanel aiDraftStage"
          :class="{ 'is-mobile-visible': mobilePreviewVisible }"
          aria-label="AI 实时脑图预览"
        >
          <div class="previewHeader">
            <el-button
              class="mobilePreviewBack"
              text
              aria-label="返回 AI 对话"
              @click="mobilePreviewVisible = false"
            >返回 AI 对话</el-button>
            <div>
              <strong>实时脑图</strong>
              <small>{{ previewSubtitle }}</small>
            </div>
            <div class="previewActions">
              <span v-if="draftDocument?.root" class="previewMetric">{{ draftNodeCount }} 节点</span>
              <span v-if="latestPreviewVersion >= 0" class="previewMetric">变化版本 {{ latestPreviewVersion }}</span>
              <el-button size="small" :disabled="!draftDocument?.root" @click="fitPreview">适应画布</el-button>
            </div>
          </div>
          <el-alert
            v-if="viewingHistoricalArtifact"
            :title="`正在查看第 ${selectedArtifactJob?.turnIndex || 1} 轮历史结果；应用与撤销仍锁定当前轮次。`"
            type="info"
            show-icon
            :closable="false"
          />
          <el-alert
            v-if="realtimeError"
            class="previewError"
            :title="realtimeError"
            type="warning"
            show-icon
            :closable="false"
          />
          <el-alert
            v-if="draftFreshnessMessage"
            class="previewError"
            :title="draftFreshnessMessage"
            :type="['stale', 'restarted'].includes(draftFreshness) ? 'warning' : 'info'"
            show-icon
            :closable="false"
          />
          <el-button
            v-if="isTerminalStatus(job?.status) && terminalHydrationState === 'error'"
            size="small"
            type="warning"
            plain
            :disabled="actionBusy"
            @click="retryTerminalHydration"
          >重试加载预览</el-button>
          <div v-if="draftDocument?.root" class="previewCanvas">
            <MindMapPreview
              key="ai-preview"
              ref="previewMindMapRef"
              :model-value="draftDocument.root"
              :layout="draftDocument.layout || 'logicalStructure'"
              :theme="draftDocument.theme?.template || 'default'"
              :theme-config="draftDocument.theme?.config || {}"
              :readonly="true"
              width="100%"
              height="100%"
              @ready="onPreviewReady"
            />
          </div>
          <div v-else class="previewEmpty" :class="{ 'is-running': waitingForFirstDraft }">
            <div class="previewEmptyIcon" aria-hidden="true"><el-icon><MagicStick /></el-icon></div>
            <div v-if="waitingForFirstDraft" class="previewWaitStatus" role="status" aria-live="polite">
              <span class="previewWaitTime" aria-hidden="true">已等待 {{ generationElapsedSeconds }} 秒</span>
              <strong>{{ firstDraftStageTitle }}</strong>
              <span>{{ firstDraftStageDescription }}</span>
            </div>
            <template v-else>
              <strong>等待生成脑图</strong>
              <span>配置任务并开始生成，或恢复最近一次任务。</span>
            </template>
          </div>
        </section>
        </Teleport>
      </main>
    </div>

    <template #footer>
      <div class="panelFooter">
        <div v-if="!messageModeActive && selectedArtifactJob?.artifactId" class="resultQuickActions">
          <el-button size="small" plain :disabled="actionBusy" :loading="downloading" @click="downloadArtifact">
            下载 .smm
          </el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && ['ready', 'needs_review'].includes(job.status)"
            size="small"
            plain
            :loading="openingLocal"
            :disabled="actionBusy"
            @click="openArtifactAsLocal"
          >打开为本地脑图</el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && job.status === 'ready' && canReplaceLocal"
            size="small"
            plain
            :loading="replacingLocal"
            :disabled="actionBusy"
            @click="replaceLocalWithArtifact"
          >替换当前本地脑图</el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && job.status === 'ready' && canInsertLocal"
            size="small"
            plain
            :loading="insertingLocal"
            :disabled="actionBusy"
            @click="insertArtifactBranch"
          >插入分支</el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && job.status === 'ready'"
            size="small"
            type="primary"
            :loading="savingCloud"
            :disabled="actionBusy"
            @click="saveCloud"
          >保存为云端脑图</el-button>
        </div>

        <div v-if="canApplyCurrentProposal || canUndoCurrentProposal" class="primaryResultAction">
          <div v-if="canApplyCurrentProposal">
            <strong>草稿已就绪</strong>
            <span>{{ sourceContext?.mindmapId
              ? '确认后直接覆盖当前脑图，并保留撤销快照'
              : '确认差异后再写入当前脑图' }}</span>
          </div>
          <div v-else>
            <strong>已应用到当前脑图</strong>
            <span>后续没有修改时可安全撤销</span>
          </div>
          <el-button
            v-if="canApplyCurrentProposal"
            type="primary"
            :loading="applying"
            :disabled="actionBusy || editorReadonly || !proposal || !diffConfirmed"
            @click="applyProposal"
          >{{ sourceContext?.mindmapId ? '覆盖当前脑图' : '应用' }}</el-button>
          <el-button
            v-else
            type="warning"
            plain
            :loading="undoing"
            :disabled="actionBusy && !undoing"
            @click="undoProposal"
          >撤销</el-button>
        </div>

        <div class="aiComposer" :class="{ 'is-discussion': discussionMode }">
          <div class="composerContextRow">
            <el-popover
              v-model:visible="contextPickerVisible"
              placement="top-start"
              :width="286"
              trigger="click"
              popper-class="mindmapAiContextPopper"
              :disabled="taskConfigurationLocked || actionBusy"
            >
              <template #reference>
                <button
                  type="button"
                  class="contextChip"
                  :disabled="taskConfigurationLocked || actionBusy"
                  aria-haspopup="menu"
                  :aria-expanded="contextPickerVisible"
                >
                  <el-icon><Paperclip /></el-icon>{{ currentContextLabel }}
                  <el-icon aria-hidden="true"><ArrowUp /></el-icon>
                </button>
              </template>
              <div class="contextMenu" role="menu" aria-label="选择 AI 上下文">
                <button
                  type="button"
                  role="menuitemradio"
                  :aria-checked="form.sourceMode === 'current' && form.scopeType === 'document'"
                  :disabled="!contextAvailability.document"
                  @click="selectComposerContext('document')"
                ><strong>整份当前脑图</strong><small>向 Agent 授权完整脑图</small></button>
                <button
                  type="button"
                  role="menuitemradio"
                  :aria-checked="form.sourceMode === 'current' && form.scopeType === 'branch'"
                  :disabled="!contextAvailability.branch"
                  @click="selectComposerContext('branch')"
                ><strong>当前分支</strong><small>需要恰好选择一个节点</small></button>
                <button
                  type="button"
                  role="menuitemradio"
                  :aria-checked="form.sourceMode === 'current' && form.scopeType === 'selectedNodes'"
                  :disabled="!contextAvailability.selectedNodes"
                  @click="selectComposerContext('selectedNodes')"
                ><strong>已选节点（{{ selectedNodeUids.length }}）</strong><small>仅授权当前选择及其子树</small></button>
                <button
                  type="button"
                  role="menuitemradio"
                  :aria-checked="form.sourceMode === 'new'"
                  :disabled="!contextAvailability.newDocument"
                  @click="selectComposerContext('new')"
                ><strong>新建脑图</strong><small>不读取当前画布</small></button>
                <button
                  type="button"
                  role="menuitemradio"
                  :aria-checked="form.sourceMode === 'file'"
                  :disabled="!contextAvailability.file"
                  @click="selectComposerContext('file')"
                ><strong>本地文件</strong><small>XMind、SMM、JSON、Markdown 或 TXT</small></button>
              </div>
            </el-popover>
            <span v-if="discussionMode" class="discussionChip">讨论模式 · 只返回回答</span>
          </div>
          <div
            v-if="agentSelectionIssue && composerEnabled && !showAdvancedSettings"
            class="composerAgentIssue"
            role="status"
          >
            <el-icon aria-hidden="true"><WarningFilled /></el-icon>
            <span>{{ agentSelectionIssue }}</span>
            <button type="button" @click="showAdvancedSettings = true">选择 Agent</button>
          </div>
          <div v-if="submitting" class="submissionStatus" role="status" aria-live="polite">
            <i aria-hidden="true"></i>
            <div>
              <strong>{{ submissionStageTitle }}</strong>
              <small>{{ submissionStageDescription }}</small>
            </div>
          </div>
          <el-input
            v-model="composerText"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            maxlength="20000"
            resize="none"
            :disabled="!composerEnabled"
            :placeholder="composerPlaceholder"
            @keydown="onComposerKeydown"
          />
          <div class="composerToolbar">
            <div class="composerTools">
              <el-tooltip
                content="添加 XMind、SMM、JSON、Markdown 或文本文件"
                placement="top"
                popper-class="mindmapAiTooltipPopper"
              >
                <el-button
                  circle
                  text
                  aria-label="添加文件"
                  :disabled="taskConfigurationLocked || actionBusy"
                  @click="selectSourceFile"
                ><el-icon><Paperclip /></el-icon></el-button>
              </el-tooltip>
              <el-tooltip
                content="展开任务与 Agent 设置"
                placement="top"
                popper-class="mindmapAiTooltipPopper"
              >
                <el-button circle text aria-label="展开设置" @click="showAdvancedSettings = true">
                  <el-icon><MoreFilled /></el-icon>
                </el-button>
              </el-tooltip>
              <el-switch
                v-model="discussionMode"
                inline-prompt
                active-text="讨论"
                inactive-text="编辑"
                :disabled="Boolean(job) && !canSwitchInteractionMode"
                aria-label="讨论模式"
              />
            </div>
            <div class="composerSubmitGroup">
              <div class="reasoningModes" aria-label="AI 生成深度">
                <button
                  v-for="mode in reasoningModes"
                  :key="mode.value"
                  type="button"
                  :class="{ 'is-active': reasoningMode === mode.value }"
                  :disabled="taskConfigurationLocked"
                  :title="mode.description"
                  @click="setReasoningMode(mode.value)"
                >{{ mode.label }}</button>
              </div>
              <el-button
                v-if="running"
                circle
                aria-label="取消任务"
                :loading="cancelling"
                :disabled="actionBusy && !cancelling"
                @click="cancelJob"
              ><el-icon v-if="!cancelling"><Close /></el-icon></el-button>
              <el-button
                v-else
                circle
                type="primary"
                aria-label="发送给 AI"
                :loading="composerSending"
                :disabled="!composerCanSend"
                @click="sendComposerMessage"
              ><el-icon v-if="!composerSending"><Promotion /></el-icon></el-button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { saveAs } from 'file-saver'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowUp,
  Close,
  DataAnalysis,
  List,
  MagicStick,
  MoreFilled,
  Paperclip,
  Plus,
  Promotion,
  Setting,
  TrendCharts,
  WarningFilled,
} from '@element-plus/icons-vue'
import { listModelAll } from '@/api/ai/model'
import useUserStore from '@/store/modules/user'
import {
  ackMindmapAiLocalApply,
  ackMindmapAiLocalUndo,
  applyMindmapAiCloudProposal,
  cancelMindmapAiJob,
  continueMindmapAiJob,
  createMindmapAiJob,
  deleteMindmapAiSession,
  downloadMindmapAiArtifact,
  getMindmapAiJob,
  getMindmapAiJobDraft,
  getMindmapAiProposal,
  getMindmapAiSessionTimeline,
  listMindmapAiSessions,
  listMindmapAiAgents,
  prepareMindmapAiLocalApply,
  reconcileMindmapAiJob,
  retryMindmapAiJob,
  saveMindmapAiArtifactCloud,
  validateMindmapAiArtifact,
  undoMindmapAiCloudProposal,
} from '@/api/mindmap/mindmap'
import {
  assertMindmapAiArtifact,
  buildMindmapAiArtifactFromDocument,
  computeMindmapSnapshotFingerprint,
  createMindmapAiIdempotencyKey,
} from '@/utils/mindmap-ai-artifact'
import { verifyMindmapAiLocalProposal } from '@/utils/mindmap-ai-proposal'
import {
  enqueueMindmapAiLocalAck,
  flushMindmapAiLocalAcks,
  listMindmapAiLocalAcks,
} from '@/utils/mindmap-ai-ack-queue'
import {
  getMindmapAiLocalJournal,
  removeMindmapAiLocalJournal,
  transitionMindmapAiLocalJournal,
} from '@/utils/mindmap-ai-local-journal'
import {
  enqueueMindmapAiCloudMutationIntent,
  getMindmapAiCloudMutationIntent,
  listMindmapAiCloudMutationIntents,
  markMindmapAiCloudMutationConfirmed,
  markMindmapAiCloudMutationFailed,
  removeMindmapAiCloudMutationIntent,
} from '@/utils/mindmap-ai-cloud-mutation-intent'
import {
  formatMindmapAiError,
  formatMindmapAiJobError,
  resolveMindmapAiErrorCode,
} from '@/utils/mindmap-ai-errors'
import {
  buildMindmapAiTimelineEnvelopeKey,
  consumeMindmapAiRealtimeEvents,
  describeMindmapAiAgentProgress,
  fingerprintMindmapAiRequest,
  mergeMindmapAiJobEventSnapshot,
  mergeMindmapAiJobSnapshot,
  resolveMindmapAiRequestAttempt,
  sanitizeMindmapAiAgentProgressPayload,
} from '@/utils/mindmap-ai-stream'
import {
  clearMindmapAiOwnerSessionItem,
  readMindmapAiOwnerSessionItem,
  writeMindmapAiOwnerSessionItem,
} from '@/utils/mindmap-ai-owner-session'
import {
  buildMindmapAiConversationTurns,
  deriveMindmapAiSessionTitle,
  isMindmapAiMessageJob,
  normalizeMindmapAiSessionList,
  resolveMindmapAiContextAvailability,
  resolveMindmapAiSessionTitle,
} from '@/utils/mindmap-ai-conversation'
import { resolveMindmapAiAgentSelection } from '@/utils/mindmap-ai-agent-selection'
import { layoutList } from './config'
import MindMapPreview from './index.vue'
import bus from './useEventBus'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})
const router = useRouter()
const userStore = useUserStore()

const intentOptions = [
  { value: 'create', label: '创建 / 完善脑图' },
  { value: 'expand', label: '扩展内容' },
  { value: 'rewrite_branch', label: '重写分支' },
  { value: 'condense_branch', label: '精简分支' },
  { value: 'reorganize', label: '重新组织结构' },
]
const outputLanguageOptions = Object.freeze([
  { value: 'zh-CN', label: '简体中文' },
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'en-US', label: 'English' },
  { value: 'ja-JP', label: '日本語' },
  { value: 'ko-KR', label: '한국어' },
])
const OUTPUT_LANGUAGE_VALUES = new Set(outputLanguageOptions.map(item => item.value))
const AI_LAYOUT_VALUES = new Set([
  'mindMap',
  'logicalStructure',
  'organizationStructure',
  'catalogOrganization',
  'timeline',
  'fishbone',
])
const aiLayoutOptions = Object.freeze(
  layoutList.filter(item => AI_LAYOUT_VALUES.has(item.value)),
)

const visible = ref(false)
const agents = ref([])
const models = ref([])
const loadingAgents = ref(false)
const agentError = ref('')
const submitting = ref(false)
const submissionStartedAt = ref(0)
const cancelling = ref(false)
const downloading = ref(false)
const savingCloud = ref(false)
const applying = ref(false)
const continuing = ref(false)
const retrying = ref(false)
const parsingFile = ref(false)
const openingLocal = ref(false)
const replacingLocal = ref(false)
const insertingLocal = ref(false)
const undoing = ref(false)
const deletingSession = ref(false)
const restoringJob = ref(false)
const job = ref(null)
const jobConfiguration = ref(null)
const proposal = ref(null)
const diffConfirmed = ref(false)
const followupPrompt = ref('')
const retryPrompt = ref('')
const selectedNodeUids = ref([])
const sourceContext = ref(null)
const editorContext = ref(null)
const sourceFingerprint = ref('')
const sourceFileInputRef = ref(null)
const previewMindMapRef = ref(null)
const activityTimelineRef = ref(null)
const proposalConfirmationRef = ref(null)
const uploadedFileName = ref('')
const uploadedFileArtifact = ref(null)
const agentEvents = ref([])
const draftDocument = shallowRef(null)
const realtimeConnectionState = ref('idle')
const realtimeError = ref('')
const draftFreshness = ref('idle')
const draftFreshnessMessage = ref('')
const proposalError = ref('')
const timelineLoading = ref(false)
const timelineError = ref('')
const restoreError = ref('')
const pendingAttemptNotice = ref('')
const cloudMutationRecoveryError = ref('')
const cloudMutationRecovering = ref(false)
const cloudMutationRetryable = ref(false)
const cloudMutationHasPermanentFailure = ref(false)
const proposalLoading = ref(false)
const terminalHydrationState = ref('idle')
const terminalHydrationError = ref('')
const selectedArtifactLoading = ref(false)
const showAdvancedSettings = ref(false)
const discussionMode = ref(false)
const mobilePreviewVisible = ref(false)
const contextPickerVisible = ref(false)
const sessionMenuVisible = ref(false)
const recentSessions = ref([])
const sessionListLoading = ref(false)
const sessionListError = ref('')
const sessionSwitching = ref(false)
const currentSessionTitle = ref('新对话')
const sessionTurns = ref([])
const selectedTurnJobId = ref('')
const artifactValidationStatuses = ref({})
const latestEventSequence = ref(0)
const latestPreviewVersion = ref(-1)
const generationClockNow = ref(Date.now())
let pollTimer = null
let pollController = null
let draftController = null
let realtimeController = null
let realtimeReconnectTimer = null
let localAckRetryTimer = null
let restoreController = null
let timelineController = null
let sessionListController = null
let terminalHydrationRetryTimer = null
let terminalHydrationRetryCount = 0
let realtimeGeneration = 0
let restoreGeneration = 0
let timelineLoadGeneration = 0
let sessionListGeneration = 0
let actionGeneration = 0
let realtimeReconnectAttempt = 0
let componentAlive = true
let submitAttempt = null
let saveCloudAttempt = null
let followupAttempt = null
let retryAttempt = null
let pendingDialogPreset = null
const cloudMutationFlushPromises = new Map()
const cloudMutationExecutions = new Map()
let proposalLoadGeneration = 0
let generationClockTimer = null
const agentEventKeys = new Set()
const agentEventEnvelopeKeys = new Set()
const jobEventSequences = new Map()
const ACTIVE_JOB_STORAGE_KEY = 'MINDMAP_AI_ACTIVE_JOB_V1'
const RECENT_JOB_STORAGE_KEY = 'MINDMAP_AI_RECENT_JOB_V1'
const ATTEMPTS_STORAGE_KEY = 'MINDMAP_AI_REQUEST_ATTEMPTS_V1'
const STORED_JOB_TTL_MS = 30 * 24 * 60 * 60 * 1000
const ATTEMPT_TTL_MS = 24 * 60 * 60 * 1000
const TERMINAL_HYDRATION_RETRY_DELAYS = [800, 1800, 4000]
const REALTIME_RECONNECT_BASE_MS = 600
const REALTIME_RECONNECT_MAX_MS = 10_000
const LOCAL_ACK_RETRY_BASE_MS = 1_000
const LOCAL_ACK_RETRY_MAX_MS = 30_000
const PERMANENT_CLOUD_MUTATION_CODES = new Set([
  'AI_PROPOSAL_STALE',
  'AI_PROPOSAL_NOT_FOUND',
  'AI_PROPOSAL_STATE_INVALID',
  'AI_PROPOSAL_INTEGRITY_INVALID',
  'AI_PROPOSAL_FORMAT_OBSOLETE',
  'AI_APPLY_CONFLICT',
  'AI_UNDO_CONFLICT',
  'AI_UNDO_NOT_FOUND',
  'AI_UNDO_STATE_INVALID',
  'AI_UNDO_SNAPSHOT_INVALID',
  'AI_CLOUD_MUTATION_SUPERSEDED',
  'AI_CLOUD_RECONCILE_STATE_INVALID',
])
const DENSITY_VALUES = new Set(['concise', 'standard', 'detailed'])
const reasoningModes = Object.freeze([
  { value: 'quick', label: '快速', description: '适合简单问题，生成更精简' },
  { value: 'balanced', label: '均衡', description: '适合日常脑图生成与优化' },
  { value: 'deep', label: '深度', description: '适合复杂主题，允许更多节点与层级' },
])
const SOURCE_MODE_VALUES = new Set(['current', 'new', 'file'])
const SCOPE_TYPE_VALUES = new Set(['document', 'branch', 'selectedNodes'])
const localAckRecoveryWarnings = new Set()
const localAckRecoveryCompleted = new Set()

const form = reactive({
  agentKey: 'native_mindmap',
  modelId: null,
  intent: 'create',
  sourceMode: 'current',
  scopeType: 'document',
  prompt: '',
  language: 'zh-CN',
  layout: 'logicalStructure',
  density: 'standard',
  maxNodes: 100,
  maxDepth: 6,
})

const terminalStatuses = new Set([
  'ready', 'applied', 'undone', 'completed_file', 'completed_no_change',
  'completed_message',
  'needs_review', 'stale', 'cancelled', 'failed', 'expired',
  'needs_input',
])
const retryableStatuses = new Set(['failed', 'cancelled', 'expired', 'stale'])
const running = computed(() => Boolean(job.value && !terminalStatuses.has(job.value.status)))
const waitingForFirstDraft = computed(() => Boolean(
  running.value
  && !messageModeActive.value
  && !draftDocument.value?.root
))
const generationElapsedSeconds = computed(() => {
  if (!running.value) return 0
  const startedAt = Date.parse(job.value?.createdTime || '')
  if (!Number.isFinite(startedAt)) return 0
  return Math.max(0, Math.floor((generationClockNow.value - startedAt) / 1000))
})
const firstDraftStageTitle = computed(() => {
  if (['queued', 'preparing'].includes(job.value?.status)) return statusLabel.value
  if (generationElapsedSeconds.value < 5) return '正在理解你的要求'
  if (generationElapsedSeconds.value < 15) return '正在准备脑图结构'
  if (job.value?.agentKey === 'native_mindmap') return '本机模型正在生成首个节点'
  return 'Agent 正在生成首个节点'
})
const firstDraftStageDescription = computed(() => {
  if (generationElapsedSeconds.value < 5) return 'Agent 正在分析主题、范围和生成约束。'
  if (generationElapsedSeconds.value < 15) return '首个节点出现后，脑图会在这里逐步展开。'
  if (job.value?.agentKey === 'native_mindmap') {
    return '首次唤醒本机模型通常需要 10–30 秒；任务仍在运行，请勿重复提交。'
  }
  return '任务仍在运行，首个节点生成后会自动显示，请勿重复提交。'
})
const retryAvailable = computed(() => Boolean(
  job.value?.id
  && retryableStatuses.has(job.value.status)
  && !running.value
))
const mutationActionBusy = computed(() => Boolean(
  submitting.value
  || cancelling.value
  || savingCloud.value
  || applying.value
  || continuing.value
  || retrying.value
  || openingLocal.value
  || replacingLocal.value
  || insertingLocal.value
  || undoing.value
  || deletingSession.value
  || sessionSwitching.value
))
const actionBusy = computed(() => restoringJob.value || mutationActionBusy.value)
const reasoningMode = computed(() => ({
  concise: 'quick',
  detailed: 'deep',
}[form.density] || 'balanced'))
const effectiveFormIntent = computed(() => discussionMode.value ? 'discuss' : form.intent)
const messageModeActive = computed(() => (
  isMindmapAiMessageJob(job.value) || (!job.value && discussionMode.value)
))
const contextAvailability = computed(() => resolveMindmapAiContextAvailability({
  selectedCount: selectedNodeUids.value.length,
  hasEditor: Boolean(editorContext.value?.document?.root),
  locked: taskConfigurationLocked.value || actionBusy.value,
}))
const currentContextLabel = computed(() => {
  if (form.sourceMode === 'file') return uploadedFileName.value || '本地文件'
  if (form.sourceMode === 'new') return '新建脑图'
  if (form.scopeType === 'selectedNodes') return `已选节点 · ${selectedNodeUids.value.length}`
  if (form.scopeType === 'branch') return '当前分支'
  return editorContext.value?.title || editorContext.value?.name || '当前脑图'
})
const composerText = computed({
  get() {
    if (!job.value) return form.prompt
    if (retryAvailable.value) return retryPrompt.value
    if (followupAvailable.value) return followupPrompt.value
    return ''
  },
  set(value) {
    if (!job.value) form.prompt = value
    else if (retryAvailable.value) retryPrompt.value = value
    else if (followupAvailable.value) followupPrompt.value = value
  },
})
const composerEnabled = computed(() => Boolean(
  !running.value
  && !actionBusy.value
  && (!job.value || retryAvailable.value || followupAvailable.value)
))
const composerPlaceholder = computed(() => {
  if (running.value) {
    return messageModeActive.value
      ? 'AI 正在回答，请稍候…'
      : 'AI 正在生成，脑图变化会实时显示在右侧'
  }
  if (job.value?.status === 'needs_input') return '补充 Agent 需要的信息…'
  if (retryAvailable.value) return '修改要求并重试这一轮…'
  if (followupAvailable.value) {
    return discussionMode.value
      ? '基于当前脑图继续讨论，不应用任何变更…'
      : '继续调整刚才的脑图…'
  }
  if (job.value) return '新建对话后继续向 AI 提问'
  return discussionMode.value ? '和 AI 讨论当前脑图，不应用任何变更…' : '问我任何问题…'
})
const composerSending = computed(() => Boolean(
  submitting.value || continuing.value || retrying.value
))
const submissionElapsedSeconds = computed(() => {
  if (!submitting.value || !submissionStartedAt.value) return 0
  return Math.max(0, Math.floor((generationClockNow.value - submissionStartedAt.value) / 1_000))
})
const submissionStageTitle = computed(() => (
  selectedAgent.value?.healthStatus === 'unknown'
    ? `正在检查 ${selectedAgent.value?.displayName || 'Agent'} 连接`
    : `正在创建 ${selectedAgent.value?.displayName || 'Agent'} 任务`
))
const submissionStageDescription = computed(() => {
  const elapsed = `已等待 ${submissionElapsedSeconds.value} 秒`
  return selectedAgent.value?.healthStatus === 'unknown'
    ? `连接通过后会立即创建任务并显示实时过程 · ${elapsed}`
    : `正在冻结输入与生成约束，请勿重复提交 · ${elapsed}`
})
const composerCanSend = computed(() => Boolean(
  composerEnabled.value
  && composerText.value.trim()
  && !restoreError.value
  && selectedAgentReady.value
))
const selectedTurn = computed(() => (
  sessionTurns.value.find(turn => String(turn?.job?.id || '') === selectedTurnJobId.value)
  || null
))
const conversationTurns = computed(() => buildMindmapAiConversationTurns({
  sessionTurns: sessionTurns.value,
  currentJob: job.value,
  events: agentEvents.value,
}))
const artifactTurns = computed(() => sessionTurns.value.filter(turn => turn?.job?.artifactId))
const selectedArtifactJob = computed(() => selectedTurn.value?.job || job.value)
const viewingHistoricalArtifact = computed(() => Boolean(
  selectedTurnJobId.value
  && job.value?.id
  && selectedTurnJobId.value !== String(job.value.id)
))
const followupParentJob = computed(() => {
  const candidate = selectedArtifactJob.value
  if (candidate?.status === 'needs_input' && !candidate.artifactId) return candidate
  if (isMindmapAiMessageJob(candidate) && candidate?.status === 'completed_message') return candidate
  if (
    !viewingHistoricalArtifact.value
    && ['cloud_document', 'local_snapshot'].includes(candidate?.sourceType)
    && ['applied', 'undone'].includes(candidate?.status)
  ) return candidate
  return candidate?.artifactId
    && ['ready', 'completed_file', 'completed_no_change', 'needs_review'].includes(candidate.status)
    ? candidate
    : null
})
const needsInputQuestions = computed(() => {
  if (job.value?.status !== 'needs_input') return []
  const requestEvent = [...agentEvents.value].reverse().find(event => (
    event.jobId === job.value.id && event.eventType === 'needs_input'
  ))
  return Array.isArray(requestEvent?.payload?.questions)
    ? requestEvent.payload.questions.filter(question => (
      typeof question?.questionId === 'string' && typeof question?.prompt === 'string'
    )).slice(0, 3)
    : []
})
const followupAvailable = computed(() => Boolean(
  followupParentJob.value
  && !running.value
  && (
    followupParentJob.value.status !== 'needs_input'
    || needsInputQuestions.value.length > 0
  )
))
const canSwitchInteractionMode = computed(() => Boolean(
  followupAvailable.value
  && followupParentJob.value?.status !== 'needs_input'
  && !running.value
  && !actionBusy.value
))
const taskConfigurationLocked = computed(() => restoringJob.value || Boolean(job.value))
const agentSelectionLocked = computed(() => (
  restoringJob.value
  || submitting.value
  || continuing.value
  || retrying.value
  || (Boolean(job.value) && !followupAvailable.value && !retryAvailable.value)
))
const editorReadonly = computed(() => Boolean(props.readonly || editorContext.value?.readonly))
const canUndoCurrentProposal = computed(() => Boolean(
  !viewingHistoricalArtifact.value
  &&
  job.value?.proposalId
  && job.value.status === 'applied'
  && (
    sourceContext.value?.mindmapId
    || (
      editorContext.value?.canUndoAiProposal === true
      && editorContext.value?.undoableAiProposalId === job.value.proposalId
    )
  )
))
const selectedAgent = computed(() => (
  agents.value.find(item => item.agentKey === form.agentKey) || null
))
const agentSelectionIssue = computed(() => {
  if (loadingAgents.value || agentError.value) return ''
  if (!form.agentKey) return agents.value.length
    ? '请选择一个支持当前任务的 AI Agent。'
    : '当前没有可用的 AI Agent，请联系管理员检查 Connector。'
  if (!selectedAgent.value) {
    return `此前选择的 Agent“${form.agentKey}”已不可用；系统不会自动替换，请手动选择其他 Agent。`
  }
  if (selectedAgent.value.status !== 'enabled') {
    return selectedAgent.value.statusReason
      || `${selectedAgent.value.displayName} 当前不可用，请稍后重试或手动选择其他 Agent。`
  }
  if (!agentSupportsCurrentTask(selectedAgent.value)) {
    return `${selectedAgent.value.displayName} 不支持当前任务或输入来源；请调整任务、来源或手动选择其他 Agent。`
  }
  if (form.agentKey === 'native_mindmap' && !form.modelId) {
    return 'MindMap Agent 没有可用模型，请选择模型或改用其他 Agent。'
  }
  return ''
})
const selectedAgentReady = computed(() => Boolean(
  !loadingAgents.value
  && !agentError.value
  && selectedAgent.value
  && !agentSelectionIssue.value
))
const selectedAgentReadinessTone = computed(() => {
  if (selectedAgent.value?.status !== 'enabled') return 'unavailable'
  if (selectedAgent.value?.healthStatus === 'healthy') return 'ready'
  if (selectedAgent.value?.healthStatus === 'unhealthy') return 'unavailable'
  return 'pending'
})
const selectedAgentReadinessLabel = computed(() => ({
  ready: `${selectedAgent.value?.displayName || 'Agent'} 连接已就绪`,
  unavailable: `${selectedAgent.value?.displayName || 'Agent'} 当前不可用`,
  pending: `${selectedAgent.value?.displayName || 'Agent'} 将在首次运行前检查连接`,
})[selectedAgentReadinessTone.value])
const selectedAgentReadinessDescription = computed(() => {
  if (selectedAgentReadinessTone.value === 'ready') {
    return selectedAgent.value?.lastHealthTime
      ? `最近检查 ${formatEventTime(selectedAgent.value.lastHealthTime)}`
      : '认证与运行环境已通过检查'
  }
  if (selectedAgentReadinessTone.value === 'unavailable') {
    return selectedAgent.value?.healthReason || selectedAgent.value?.statusReason || '请联系管理员检查 Connector'
  }
  return '提交后会自动校验认证和 SDK 状态，通过后立即开始生成'
})
const maxNodesCap = computed(() => Number(selectedAgent.value?.maxNodes || 2000))
const maxDepthCap = computed(() => Number(selectedAgent.value?.maxDepth || 32))
const targetLayoutLocked = computed(() => (
  form.sourceMode === 'current' && form.scopeType !== 'document'
))
const targetLayoutHint = computed(() => '局部编辑只修改授权节点，保持当前脑图布局。')
const availableModels = computed(() => {
  const allowlist = Array.isArray(selectedAgent.value?.modelAllowlist)
    ? selectedAgent.value.modelAllowlist.map(String)
    : []
  if (!allowlist.length) return models.value
  return models.value.filter(model => allowlist.includes(String(model.modelId)))
})
const canReplaceLocal = computed(() => !editorContext.value?.mindmapId && !editorReadonly.value)
const canInsertLocal = computed(() => (
  canReplaceLocal.value && selectedNodeUids.value.length === 1
))
const currentProposalSourceAvailable = computed(() => {
  if (job.value?.sourceType !== 'local_snapshot') return true
  return Boolean(
    sourceContext.value?.documentId
    && sourceContext.value?.document?.root
    && sourceFingerprint.value,
  )
})
const canApplyCurrentProposal = computed(() => Boolean(
  !viewingHistoricalArtifact.value
  && !messageModeActive.value
  && currentProposalSourceAvailable.value
  && job.value?.proposalId
  && job.value.status === 'ready'
))
const proposalReviewFinalized = computed(() => Boolean(
  proposal.value
  && ['applied', 'undone'].includes(job.value?.status)
))
const jobStatusLabels = {
  queued: '任务已排队',
  preparing: '正在准备安全上下文',
  running: 'Agent 正在构建脑图',
  validating: '正在校验 SMM v2',
  cancel_requested: '正在取消',
  ready: '结果已就绪',
  applied: '已应用',
  undone: '已撤销',
  completed_file: '已保存为云端脑图',
  completed_message: 'AI 已回复',
  completed_no_change: '未发现需要应用的变化',
  cancelled: '任务已取消',
  failed: '任务失败',
  expired: '结果已过期',
  stale: '基线已过期',
  needs_review: '需要人工确认',
  needs_input: '等待补充信息',
}
function displayJobStatusLabel(candidate) {
  const status = candidate?.status
  if (isMindmapAiMessageJob(candidate)) {
    if (status === 'running') return 'Agent 正在思考'
    if (status === 'validating') return '正在整理回答'
  }
  return jobStatusLabels[status] || status || '等待开始'
}
const statusLabel = computed(() => displayJobStatusLabel(job.value))
const jobErrorMessage = computed(() => formatMindmapAiJobError(job.value, 'AI 脑图任务失败'))
const connectionStateLabel = computed(() => {
  if (
    realtimeConnectionState.value === 'connected'
    && ['queued', 'preparing'].includes(job.value?.status)
  ) return statusLabel.value
  if (
    realtimeConnectionState.value === 'connected'
    && running.value
    && !draftDocument.value?.root
    && draftFreshness.value === 'unavailable'
  ) return '已连接 · 正在生成首个节点'
  if (
    realtimeConnectionState.value === 'connected'
    && ['stale', 'unavailable', 'restarted'].includes(draftFreshness.value)
  ) return '已连接 · 草稿非实时'
  if (realtimeConnectionState.value === 'completed') {
    if (job.value?.status === 'failed') return '运行结束'
    if (job.value?.status === 'cancelled') return '已取消'
    return '已完成'
  }
  return ({
    connecting: '正在连接',
    connected: '实时运行',
    reconnecting: '正在重连',
    offline: '离线',
    idle: '待命',
  })[realtimeConnectionState.value] || '待命'
})
const draftNodeCount = computed(() => countDraftNodes(draftDocument.value?.root))
const previewSubtitle = computed(() => {
  if (viewingHistoricalArtifact.value) return `第 ${selectedArtifactJob.value?.turnIndex || 1} 轮只读历史结果`
  if (draftDocument.value?.root) return running.value ? '随 Agent 操作实时更新' : '当前任务的最新权威草稿'
  return running.value
    ? `${statusLabel.value} · 已等待 ${generationElapsedSeconds.value} 秒`
    : '只读预览画布'
})
const progressStatus = computed(() => {
  if (job.value?.status === 'failed') return 'exception'
  if (['ready', 'applied', 'completed_file', 'completed_message'].includes(job.value?.status)) return 'success'
  return undefined
})

function isAbortError(error) {
  return error?.name === 'AbortError'
    || error?.name === 'CanceledError'
    || error?.code === 'ERR_CANCELED'
}

function isHttpNotFound(error) {
  return Number(error?.response?.status ?? error?.status) === 404
}

function isTerminalStatus(status) {
  return terminalStatuses.has(status)
}

function cloneRuntimeValue(value) {
  if (value == null) return value
  try {
    return JSON.parse(JSON.stringify(value))
  } catch {
    return null
  }
}

function currentAiOwnerUserId() {
  const ownerUserId = String(userStore.id ?? '').trim()
  return /^[1-9]\d{0,63}$/.test(ownerUserId) ? ownerUserId : ''
}

function confirmMindmapAiLocalJournalAck(ownerUserId, proposalId, payload, action) {
  const identity = {
    ownerUserId,
    proposalId,
    documentId: payload?.documentId,
  }
  let entry
  try {
    entry = getMindmapAiLocalJournal(identity)
    if (!entry) return false
    if (action === 'undo') {
      if (entry.phase === 'prepared') {
        entry = transitionMindmapAiLocalJournal(identity, 'applied_ack_pending')
      }
      if (entry?.phase === 'applied_ack_pending') {
        entry = transitionMindmapAiLocalJournal(identity, 'applied_ack_confirmed')
      }
      if (entry?.phase === 'applied_ack_confirmed') {
        entry = transitionMindmapAiLocalJournal(identity, 'undone_ack_pending')
      }
      if (entry?.phase === 'undone_ack_pending') {
        transitionMindmapAiLocalJournal(identity, 'done')
        removeMindmapAiLocalJournal(identity)
      }
      return true
    }
    if (entry.phase === 'prepared') {
      entry = transitionMindmapAiLocalJournal(identity, 'applied_ack_pending')
    }
    if (entry?.phase === 'applied_ack_pending') {
      transitionMindmapAiLocalJournal(identity, 'applied_ack_confirmed')
    }
    return true
  } catch (error) {
    // 服务端回执已经成功，日志回写失败不能回滚画布；保留日志并在下次
    // 打开时通过服务端幂等状态重新对账。
    console.warn('AI 本地事务日志回执阶段暂未更新:', error)
    return false
  }
}

function invalidateActionIdentity() {
  actionGeneration += 1
}

function beginActionIdentity(type, expected = {}) {
  return {
    type,
    generation: ++actionGeneration,
    ownerUserId: currentAiOwnerUserId(),
    jobId: expected.jobId ?? job.value?.id ?? null,
    proposalId: expected.proposalId ?? null,
    artifactId: expected.artifactId ?? null,
  }
}

function actionIdentityMatches(identity) {
  if (!identity || identity.generation !== actionGeneration || !componentAlive) return false
  if (!identity.ownerUserId || identity.ownerUserId !== currentAiOwnerUserId()) return false
  if (identity.jobId && String(job.value?.id || '') !== String(identity.jobId)) return false
  if (identity.proposalId && String(job.value?.proposalId || '') !== String(identity.proposalId)) return false
  if (identity.artifactId && String(job.value?.artifactId || '') !== String(identity.artifactId)) return false
  return true
}

function assertActionIdentity(identity) {
  if (actionIdentityMatches(identity)) return true
  const error = new Error('操作上下文已变化，已忽略过期响应')
  error.code = 'AI_ACTION_SUPERSEDED'
  throw error
}

function readPersistedAttempts() {
  try {
    const ownerUserId = currentAiOwnerUserId()
    if (!ownerUserId) return {}
    const parsed = JSON.parse(
      readMindmapAiOwnerSessionItem(ATTEMPTS_STORAGE_KEY, ownerUserId) || '{}',
    )
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return Object.fromEntries(Object.entries(parsed).filter(([, item]) => (
      item?.key
      && item?.fingerprintHash
      && item?.ownerUserId === ownerUserId
      && Date.now() - Number(item.savedAt) <= ATTEMPT_TTL_MS
    )))
  } catch {
    return {}
  }
}

function writePersistedAttempts(attempts) {
  try {
    const ownerUserId = currentAiOwnerUserId()
    if (!ownerUserId) return false
    return writeMindmapAiOwnerSessionItem(
      ATTEMPTS_STORAGE_KEY,
      ownerUserId,
      JSON.stringify(attempts),
    )
  } catch {
    return false
  }
}

async function hashAttemptFingerprint(fingerprint) {
  const bytes = new TextEncoder().encode(String(fingerprint || ''))
  if (!globalThis.crypto?.subtle) throw new Error('当前浏览器无法安全保存请求恢复标识')
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

async function resolveDurableAttempt(type, currentAttempt, payload, {
  createKey,
  metadata = {},
} = {}) {
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId) throw new Error('当前登录用户身份尚未就绪，无法保存 AI 请求恢复标识')
  const fingerprint = fingerprintMindmapAiRequest(payload)
  const fingerprintHash = await hashAttemptFingerprint(fingerprint)
  const persistedAttempts = readPersistedAttempts()
  const persisted = persistedAttempts[type]
  const reusingPersistedAttempt = persisted?.fingerprintHash === fingerprintHash
  const candidate = reusingPersistedAttempt
    ? { key: persisted.key, fingerprint }
    : resolveMindmapAiRequestAttempt(currentAttempt, payload, { createKey })
  persistedAttempts[type] = {
    ...(reusingPersistedAttempt ? cloneRuntimeValue(persisted) : {}),
    ...(!reusingPersistedAttempt ? cloneRuntimeValue(metadata) : {}),
    ownerUserId,
    key: candidate.key,
    fingerprintHash,
    savedAt: reusingPersistedAttempt ? persisted.savedAt : Date.now(),
  }
  if (!writePersistedAttempts(persistedAttempts)) {
    throw new Error('浏览器无法保存 AI 请求恢复标识，已阻止发送以避免重复任务')
  }
  return candidate
}

function clearDurableAttempt(type, key = '') {
  const attempts = readPersistedAttempts()
  if (!attempts[type] || (key && attempts[type].key !== key)) return
  delete attempts[type]
  writePersistedAttempts(attempts)
}

function restoreDurableAttemptNotice() {
  const attempts = readPersistedAttempts()
  const pendingTypes = Object.keys(attempts)
  pendingAttemptNotice.value = pendingTypes.length
    ? '检测到结果尚未确认的请求；再次提交相同内容会复用原请求号，并优先恢复服务端已创建的最新轮次。'
    : ''
  const followup = attempts.followup
  if (followup?.requestPayload?.prompt && !followupPrompt.value) {
    followupPrompt.value = String(followup.requestPayload.prompt)
  }
  const retry = attempts.retry
  if (retry?.requestPayload?.prompt && !retryPrompt.value) {
    retryPrompt.value = String(retry.requestPayload.prompt)
  }
}

function artifactValidationStatus(artifactId) {
  return artifactValidationStatuses.value[String(artifactId || '')] || ''
}

function isDraftArtifact(artifactId) {
  return artifactValidationStatus(artifactId) === 'draft'
}

function invalidateRestoreOperations({ clearError = true } = {}) {
  restoreGeneration += 1
  timelineLoadGeneration += 1
  restoreController?.abort()
  restoreController = null
  timelineController?.abort()
  timelineController = null
  restoringJob.value = false
  timelineLoading.value = false
  if (clearError) restoreError.value = ''
}

function captureJobConfiguration(overrides = {}) {
  return {
    agentKey: overrides.agentKey ?? form.agentKey,
    modelId: overrides.modelId ?? form.modelId ?? null,
    intent: overrides.intent ?? form.intent,
    sourceMode: overrides.sourceMode ?? form.sourceMode,
    scopeType: overrides.scopeType ?? form.scopeType,
    language: overrides.language ?? form.language,
    layout: overrides.layout ?? form.layout,
    density: overrides.density ?? form.density,
    maxNodes: Number(overrides.maxNodes ?? form.maxNodes),
    maxDepth: Number(overrides.maxDepth ?? form.maxDepth),
    interactionMode: overrides.interactionMode
      ?? (discussionMode.value ? 'discussion' : 'edit'),
  }
}

function normalizeDialogPreset(preset) {
  if (!preset || typeof preset !== 'object' || Array.isArray(preset)) return null
  const normalized = {}
  if (intentOptions.some(item => item.value === preset.intent)) normalized.intent = preset.intent
  if (SOURCE_MODE_VALUES.has(preset.sourceMode)) normalized.sourceMode = preset.sourceMode
  if (SCOPE_TYPE_VALUES.has(preset.scopeType)) normalized.scopeType = preset.scopeType
  if (OUTPUT_LANGUAGE_VALUES.has(preset.language)) normalized.language = preset.language
  if (AI_LAYOUT_VALUES.has(preset.layout)) normalized.layout = preset.layout
  if (['edit', 'discussion'].includes(preset.interactionMode)) {
    normalized.interactionMode = preset.interactionMode
  }
  if (typeof preset.prompt === 'string') normalized.prompt = preset.prompt
  return Object.keys(normalized).length ? normalized : null
}

function applyDialogPreset(preset) {
  if (!preset) return false
  const { interactionMode, ...formPreset } = preset
  Object.assign(form, formPreset)
  if (interactionMode) discussionMode.value = interactionMode === 'discussion'
  return true
}

function readUsableStoredJob(storageKey) {
  try {
    const ownerUserId = currentAiOwnerUserId()
    if (!ownerUserId) return null
    const candidate = JSON.parse(
      readMindmapAiOwnerSessionItem(storageKey, ownerUserId) || 'null',
    )
    if (
      !candidate?.jobId
      || candidate.ownerUserId !== ownerUserId
      || !Number.isFinite(Number(candidate.savedAt))
      || Date.now() - Number(candidate.savedAt) > STORED_JOB_TTL_MS
    ) return null
    return candidate
  } catch {
    return null
  }
}

function applyRecentJobDefaults(preset) {
  if (!preset || readUsableStoredJob(ACTIVE_JOB_STORAGE_KEY)) return false
  const recent = readUsableStoredJob(RECENT_JOB_STORAGE_KEY)
  const configuration = recent?.configuration
  if (!configuration || typeof configuration !== 'object') return false
  const explicitFields = new Set(Object.keys(preset))
  const restorableFields = [
    'agentKey', 'modelId', 'intent', 'sourceMode', 'scopeType',
    'language', 'layout', 'density', 'maxNodes', 'maxDepth',
  ]
  for (const field of restorableFields) {
    if (!explicitFields.has(field) && configuration[field] !== undefined) {
      form[field] = configuration[field]
    }
  }
  if (
    !explicitFields.has('interactionMode')
    && ['edit', 'discussion'].includes(configuration.interactionMode)
  ) discussionMode.value = configuration.interactionMode === 'discussion'
  return true
}

function restoreJobConfiguration(snapshot, saved = {}) {
  const stored = saved?.configuration && typeof saved.configuration === 'object'
    ? saved.configuration
    : {}
  const restoredDiscussionMode = isMindmapAiMessageJob(snapshot)
    || stored.interactionMode === 'discussion'
  const storedEditIntent = intentOptions.some(item => item.value === stored.intent)
    ? stored.intent
    : null
  const snapshotEditIntent = intentOptions.some(item => item.value === snapshot.intent)
    ? snapshot.intent
    : null
  // `discuss` is a turn mode rather than the editor action to use when the
  // user switches back. Keep the persisted editor intent for that next turn.
  const intent = snapshot.intent === 'discuss'
    ? (storedEditIntent || 'create')
    : (snapshotEditIntent || storedEditIntent || 'create')
  const sourceType = saved.sourceType || snapshot.sourceType
  const sourceMode = SOURCE_MODE_VALUES.has(stored.sourceMode)
    ? stored.sourceMode
    : sourceType === 'none'
      ? 'new'
      : sourceType === 'uploaded_artifact' ? 'file' : 'current'
  const density = DENSITY_VALUES.has(stored.density) ? stored.density : 'standard'
  const language = OUTPUT_LANGUAGE_VALUES.has(stored.language) ? stored.language : 'zh-CN'
  const layout = AI_LAYOUT_VALUES.has(stored.layout) ? stored.layout : form.layout
  const scopeType = SCOPE_TYPE_VALUES.has(stored.scopeType) ? stored.scopeType : 'document'
  const maxNodes = Number.isSafeInteger(Number(stored.maxNodes ?? snapshot.maxNodes))
    ? Number(stored.maxNodes ?? snapshot.maxNodes)
    : form.maxNodes
  const maxDepth = Number.isSafeInteger(Number(stored.maxDepth ?? snapshot.maxDepth))
    ? Number(stored.maxDepth ?? snapshot.maxDepth)
    : form.maxDepth

  form.intent = intent
  form.sourceMode = sourceMode
  form.scopeType = scopeType
  form.language = language
  form.layout = layout
  form.density = density
  discussionMode.value = restoredDiscussionMode
  if (agents.value.some(item => item.agentKey === snapshot.agentKey)) {
    form.agentKey = snapshot.agentKey
    onAgentChange()
  }
  if (form.agentKey === 'native_mindmap') {
    const restoredModelRef = stored.modelId ?? snapshot.modelRef
    const restoredModel = availableModels.value.find(model => (
      String(model.modelId) === String(restoredModelRef ?? '')
    ))
    form.modelId = restoredModel?.modelId ?? null
  }
  // 展示任务实际使用的不可变限制，即使管理员之后收紧了 Connector 上限；
  // 继续生成仍由服务端按原任务参数与最新策略做最终校验。
  form.maxNodes = maxNodes
  form.maxDepth = maxDepth
  jobConfiguration.value = captureJobConfiguration()
}

function restoreJobSourceState(snapshot, saved = {}) {
  restoreJobConfiguration(snapshot, saved)
  const sourceType = saved.sourceType || snapshot.sourceType
  const sourceMatchesEditor = (
    sourceType === 'cloud_document'
    && Number(editorContext.value?.mindmapId) === Number(saved.sourceMindmapId)
  ) || (
    sourceType === 'local_snapshot'
    && editorContext.value?.documentId === saved.sourceDocumentId
  )
  sourceContext.value = {
    mindmapId: saved.sourceMindmapId,
    documentId: saved.sourceDocumentId,
    revision: saved.sourceRevision,
    document: sourceMatchesEditor ? editorContext.value?.document : null,
    readonly: sourceMatchesEditor ? Boolean(editorContext.value?.readonly || props.readonly) : false,
  }
  sourceFingerprint.value = saved.sourceFingerprint || ''
  if (sourceContext.value.document?.root) {
    draftDocument.value = cloneRuntimeValue(sourceContext.value.document)
  }
}

function countDraftNodes(root) {
  if (!root) return 0
  let count = 0
  const pending = [root]
  while (pending.length) {
    const node = pending.pop()
    if (!node) continue
    count += 1
    pending.push(...(Array.isArray(node.children) ? node.children : []))
  }
  return count
}

function formatEventTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

function formatSessionTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function formatUsageCost(value) {
  const cost = Number(value)
  if (!Number.isFinite(cost) || cost < 0) return '0'
  if (cost === 0) return '0'
  return cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)
}

function visibleTurnEvents(turn) {
  return Array.isArray(turn?.events) ? turn.events.slice(-20) : []
}

function assistantMessageText(turn) {
  const assistantContent = String(turn?.assistantMessage?.content || '').trim()
  if (assistantContent) return assistantContent
  const turnJob = turn?.job || {}
  if (turnJob.status === 'needs_input') return '我还需要一些信息，请根据上方问题补充后继续。'
  if (turnJob.status === 'completed_message') return '回答已完成，正在同步会话正文…'
  if (turnJob.status === 'failed') {
    return formatMindmapAiJobError(turnJob, '本轮任务失败，请调整要求或重试。')
  }
  if (turnJob.status === 'cancelled') return '本轮任务已取消。'
  if (turnJob.status === 'expired') return '本轮结果已过期，可以基于原要求重新生成。'
  if (turnJob.status === 'needs_review') return '脑图草稿已生成，仍有部分内容需要人工确认。'
  if (turnJob.status === 'completed_no_change') return '已完成分析，当前脑图不需要应用新的结构变化。'
  if (['ready', 'applied', 'undone', 'completed_file'].includes(turnJob.status)) {
    const completedEvent = [...(turn?.events || [])].reverse().find(event => (
      event?.eventType === 'agent_completed'
    ))
    const nodeCount = Number(completedEvent?.payload?.summary?.nodeCount)
    const title = String(turnJob.title || '脑图结果').trim()
    return Number.isFinite(nodeCount)
      ? `${title}已生成，共 ${nodeCount} 个节点。`
      : `${title}已生成，可以在右侧预览并检查差异。`
  }
  const latestEvent = [...(turn?.events || [])].reverse()[0]
  return latestEvent ? eventDescription(latestEvent, turnJob) : 'AI 正在准备本轮任务…'
}

function sessionStatusLabel(session) {
  if (session?.currentJob) return displayJobStatusLabel(session.currentJob)
  return jobStatusLabels[session?.status] || session?.status || '未知状态'
}

function sessionUnavailableReason(session) {
  const sessionJob = session?.currentJob
  if (!sessionJob?.id) return '该会话缺少可恢复的任务'
  if (
    sessionJob.sourceType === 'cloud_document'
    && Number(sessionJob.sourceMindmapId) !== Number(editorContext.value?.mindmapId)
  ) return '该对话属于另一份云端脑图，请在原脑图中打开'
  return ''
}

function eventTypeLabel(event) {
  if (event?.eventType === 'user_prompt') return '用户要求'
  return ({
    job_created: '任务创建',
    status_changed: '任务状态',
    generation_restarted: '生成进程重启',
    draft_initialized: '草稿初始化',
    draft_changed: '脑图变更',
    agent_started: 'Agent 启动',
    agent_response: 'Agent 响应',
    agent_event: 'Agent 运行事件',
    agent_completed: 'Agent 完成',
    agent_progress: 'Agent 进度',
    agent_error: 'Agent 异常',
    tool_started: '工具开始',
    tool_completed: '工具完成',
    tool_failed: '工具失败',
    tool_plan_received: '执行计划',
    tool_plan_failed: '计划失败',
    artifact_ready: '结果就绪',
    artifact_needs_review: '等待审核',
    artifact_no_change: '无内容变化',
    cancel_requested: '取消请求',
    local_applied: '本地应用',
    local_undone: '本地撤销',
    cloud_file_created: '云端文件',
    cloud_applied: '云端应用',
    cloud_undone: '云端撤销',
    proposal_stale: '提案过期',
    needs_input: '需要补充信息',
    stream_error: '实时流异常',
  })[event?.eventType] || '安全审计'
}

function toolDisplayName(value) {
  return ({
    read_projection: '读取授权范围',
    start_document: '创建脑图',
    add_nodes: '新增节点',
    update_nodes: '更新节点',
    move_nodes: '移动节点',
    remove_nodes: '删除节点',
    set_document_meta: '更新文档设置',
    validate_draft: '校验草稿',
    complete_artifact: '生成结果文件',
    mindmap_tool: '脑图工具',
  })[String(value || '')] || '脑图工具'
}

function eventDescription(event, turnJob = job.value) {
  const payload = event?.payload || {}
  if (event?.eventType === 'user_prompt') return String(payload.message || '已提交脑图要求')
  if (event?.eventType === 'job_created') {
    const turnIndex = Number(payload.turnIndex)
    if (payload.retryOfJobId) {
      return Number.isSafeInteger(turnIndex) && turnIndex > 1
        ? `已创建第 ${turnIndex} 轮重试任务 · 使用全新 Agent 会话`
        : '已创建重试任务 · 使用全新 Agent 会话'
    }
    if (payload.sessionMode === 'new' && Number.isSafeInteger(turnIndex) && turnIndex > 1) {
      return `已创建第 ${turnIndex} 轮补充信息任务 · 使用全新 Agent 会话`
    }
    return Number.isSafeInteger(turnIndex) && turnIndex > 1
      ? `已创建第 ${turnIndex} 轮任务`
      : '已创建 AI 脑图任务'
  }
  if (event?.eventType === 'agent_progress') return describeMindmapAiAgentProgress(payload)
  if (event?.eventType === 'needs_input') {
    const count = Array.isArray(payload.questions) ? payload.questions.length : 0
    return count ? `Agent 请求补充 ${count} 项必要信息` : 'Agent 请求补充必要信息'
  }
  if (event?.eventType === 'status_changed') {
    const label = displayJobStatusLabel({ ...(turnJob || {}), status: payload.status })
    return Number.isFinite(Number(payload.progress)) ? `${label} · ${Number(payload.progress)}%` : label
  }
  if (event?.eventType === 'generation_restarted') {
    return '生成进程已重启，已从持久草稿恢复'
  }
  if (event?.eventType === 'draft_initialized') return '已建立安全的只读草稿预览'
  if (event?.eventType === 'draft_changed') {
    const count = Number(payload.changeCount) || 0
    const version = Number(payload.previewVersion)
    return `草稿更新 ${count} 项${Number.isInteger(version) ? ` · 版本 ${version}` : ''}`
  }
  if (event?.eventType === 'agent_started') return 'Agent 已开始处理本轮要求'
  if (event?.eventType === 'agent_response') return '已收到 Agent 的结构化响应'
  if (event?.eventType === 'agent_event') {
    return ({
      SystemMessage: 'Agent 运行环境已就绪',
      AssistantMessage: '模型已返回一轮安全响应',
      UserMessage: '脑图工具结果已反馈给 Agent',
      StreamEvent: '模型正在生成响应',
      RateLimitEvent: '已收到供应商用量状态',
      ConversationResetMessage: 'Agent 会话上下文已安全重置',
    })[payload.messageType] || 'Agent 已更新运行状态'
  }
  if (event?.eventType === 'agent_completed') {
    const nodeCount = Number(payload.summary?.nodeCount)
    return Number.isFinite(nodeCount) ? `Agent 已完成生成 · ${nodeCount} 个节点` : 'Agent 已完成本轮生成'
  }
  if (event?.eventType === 'tool_started') return `开始执行：${toolDisplayName(payload.toolName)}`
  if (event?.eventType === 'tool_completed') return `执行完成：${toolDisplayName(payload.toolName)}`
  if (event?.eventType === 'tool_failed') {
    const details = []
    if (typeof payload.errorCode === 'string' && payload.errorCode) {
      details.push(payload.errorCode.slice(0, 80))
    }
    if (typeof payload.errorMessage === 'string' && payload.errorMessage) {
      details.push(payload.errorMessage.slice(0, 240))
    }
    if (typeof payload.retryable === 'boolean') {
      details.push(payload.retryable ? '可重试' : '不可重试')
    }
    return `执行失败：${toolDisplayName(payload.toolName)}${details.length ? ` · ${details.join(' · ')}` : ''}`
  }
  if (event?.eventType === 'tool_plan_received') {
    return `已接收 ${Number(payload.actionCount) || 0} 项结构化操作计划`
  }
  if (event?.eventType === 'tool_plan_failed') return '结构化操作计划未通过安全校验'
  if (event?.eventType === 'artifact_ready') return '结果文件与提案已通过校验'
  if (event?.eventType === 'artifact_needs_review') return '结果已生成，部分内容需要人工确认'
  if (event?.eventType === 'artifact_no_change') return '校验完成，没有发现需要应用的变化'
  if (event?.eventType === 'cancel_requested') return '已收到取消请求，正在安全停止 Agent'
  if (event?.eventType === 'local_applied') return '提案已应用到当前本地脑图'
  if (event?.eventType === 'local_undone') return '本地 AI 提案已安全撤销'
  if (event?.eventType === 'cloud_file_created') return '结果已另存为新的云端脑图'
  if (event?.eventType === 'cloud_applied') return '提案已应用到云端脑图并同步权威版本'
  if (event?.eventType === 'cloud_undone') return '云端 AI 提案已安全撤销'
  if (event?.eventType === 'proposal_stale') return '脑图基线已经变化，该提案需要重新生成'
  if (['agent_error', 'stream_error'].includes(event?.eventType)) return '运行发生异常，详情请查看任务状态'
  return '已记录一条经过清洗的运行审计事件'
}

function fitPreview() {
  previewMindMapRef.value?.getInstance?.()?.view?.fit?.()
}

function onPreviewReady(instance) {
  requestAnimationFrame(() => instance?.view?.fit?.())
}

function clearStoredActiveJob() {
  clearMindmapAiOwnerSessionItem(ACTIVE_JOB_STORAGE_KEY, currentAiOwnerUserId())
}

function clearStoredRecentJob() {
  clearMindmapAiOwnerSessionItem(RECENT_JOB_STORAGE_KEY, currentAiOwnerUserId())
}

function clearAgentRuntimeState() {
  agentEvents.value = []
  agentEventKeys.clear()
  agentEventEnvelopeKeys.clear()
  jobEventSequences.clear()
  draftDocument.value = null
  latestEventSequence.value = 0
  latestPreviewVersion.value = -1
  realtimeConnectionState.value = 'idle'
  realtimeError.value = ''
  draftFreshness.value = 'idle'
  draftFreshnessMessage.value = ''
  timelineLoading.value = false
  timelineError.value = ''
  sessionTurns.value = []
  selectedTurnJobId.value = ''
  artifactValidationStatuses.value = {}
  terminalHydrationState.value = 'idle'
  terminalHydrationError.value = ''
  terminalHydrationRetryCount = 0
  clearTimeout(terminalHydrationRetryTimer)
  terminalHydrationRetryTimer = null
}

function stopRealtime(state = 'idle') {
  realtimeGeneration += 1
  clearTimeout(realtimeReconnectTimer)
  realtimeReconnectTimer = null
  realtimeController?.abort()
  realtimeController = null
  realtimeReconnectAttempt = 0
  realtimeConnectionState.value = state
}

function stopPolling() {
  clearTimeout(pollTimer)
  pollTimer = null
  pollController?.abort()
  pollController = null
  draftController?.abort()
  draftController = null
}

function resetNewJob({ clearStoredJob = true, preserveForm = true } = {}) {
  invalidateActionIdentity()
  invalidateRestoreOperations()
  stopRealtime('idle')
  stopPolling()
  job.value = null
  jobConfiguration.value = null
  proposal.value = null
  proposalError.value = ''
  proposalLoadGeneration += 1
  proposalLoading.value = false
  diffConfirmed.value = false
  followupPrompt.value = ''
  retryPrompt.value = ''
  sourceContext.value = null
  sourceFingerprint.value = ''
  submitAttempt = null
  saveCloudAttempt = null
  followupAttempt = null
  retryAttempt = null
  clearAgentRuntimeState()
  currentSessionTitle.value = '新对话'
  mobilePreviewVisible.value = false
  contextPickerVisible.value = false
  sessionMenuVisible.value = false
  if (clearStoredJob) {
    clearStoredActiveJob()
    clearStoredRecentJob()
  }
  if (!preserveForm) {
    form.prompt = ''
    form.intent = 'create'
    form.sourceMode = editorContext.value ? 'current' : 'new'
    form.language = 'zh-CN'
    form.layout = normalizedSourceLayout(editorContext.value?.document)
  }
  restoreDurableAttemptNotice()
}

function appendAgentEvent(jobId, event) {
  const sequence = Number(event?.data?.sequence ?? event?.id)
  if (!Number.isInteger(sequence) || sequence < 1) return false
  const key = `server:${jobId}:${sequence}`
  if (agentEventKeys.has(key)) return false
  const eventType = String(event?.eventType || event?.data?.eventType || 'message')
  const rawPayload = event?.data?.payload
  const envelopeKey = buildMindmapAiTimelineEnvelopeKey(jobId, eventType, rawPayload)
  agentEventKeys.add(key)
  const previousSequence = Number(jobEventSequences.get(jobId)) || 0
  jobEventSequences.set(jobId, Math.max(previousSequence, sequence))
  if (job.value?.id === jobId) latestEventSequence.value = jobEventSequences.get(jobId)
  if (envelopeKey && agentEventEnvelopeKeys.has(envelopeKey)) return true
  if (envelopeKey) agentEventEnvelopeKeys.add(envelopeKey)
  const payload = eventType === 'agent_progress'
    ? sanitizeMindmapAiAgentProgressPayload(rawPayload)
    : cloneRuntimeValue(rawPayload) || {}
  const record = {
    key,
    jobId,
    sequence,
    eventType,
    payload,
    createdTime: event?.data?.createdTime || new Date().toISOString(),
  }
  agentEvents.value = [...agentEvents.value, record]
  return true
}

function appendClientPrompt(jobId, prompt, turnIndex = 1, createdTime = new Date().toISOString()) {
  const key = `client:${jobId}:prompt`
  if (agentEventKeys.has(key)) return
  agentEventKeys.add(key)
  agentEvents.value = [...agentEvents.value, {
    key,
    jobId,
    sequence: 0,
    eventType: 'user_prompt',
    payload: { message: String(prompt || ''), turnIndex },
    createdTime,
  }]
}

function resetCurrentJobCursor(jobId) {
  jobEventSequences.set(jobId, 0)
  latestEventSequence.value = 0
}

function syncCurrentJobCursor(jobId) {
  latestEventSequence.value = Math.max(0, Number(jobEventSequences.get(jobId)) || 0)
}

function acceptDraftPreview(preview, { realtimeFrame = false } = {}) {
  if (messageModeActive.value) return false
  if (selectedTurnJobId.value && selectedTurnJobId.value !== String(job.value?.id || '')) {
    return false
  }
  if (preview?.available !== true) {
    if (draftFreshness.value === 'restarted') return false
    const hasVisibleDraft = Boolean(draftDocument.value?.root)
    draftFreshness.value = hasVisibleDraft ? 'stale' : 'unavailable'
    draftFreshnessMessage.value = hasVisibleDraft
      ? '实时草稿缓存暂时不可用；当前画面是最后一次成功恢复的版本，可能不是最新结果。'
      : '实时草稿暂时不可恢复；Agent 仍会继续运行，最终结果就绪后会自动重新加载。'
    return false
  }
  const version = Number(preview?.operationCursor)
  if (
    !preview.document?.root
    || !Number.isInteger(version)
    || version <= latestPreviewVersion.value
  ) return false
  latestPreviewVersion.value = version
  draftDocument.value = cloneRuntimeValue(preview.document)
  if (draftFreshness.value !== 'restarted' || realtimeFrame) {
    draftFreshness.value = 'fresh'
    draftFreshnessMessage.value = ''
  }
  return Boolean(draftDocument.value?.root)
}

function hasUnresolvedGenerationRestart(jobId = job.value?.id) {
  const jobEvents = agentEvents.value.filter(event => (
    String(event?.jobId || '') === String(jobId || '')
  ))
  const lastRestartSequence = Math.max(0, ...jobEvents
    .filter(event => event.eventType === 'generation_restarted')
    .map(event => Number(event.sequence) || 0))
  const lastDraftSequence = Math.max(0, ...jobEvents
    .filter(event => ['draft_initialized', 'draft_changed'].includes(event.eventType))
    .map(event => Number(event.sequence) || 0))
  return lastRestartSequence > lastDraftSequence
}

function markGenerationRestarted() {
  if (messageModeActive.value || isTerminalStatus(job.value?.status)) return
  draftFreshness.value = 'restarted'
  draftFreshnessMessage.value = draftDocument.value?.root
    ? '生成进程已重启；当前保留从持久检查点恢复的草稿。收到新的草稿帧前，该画面不代表最新结果。'
    : '生成进程已重启，正在恢复持久草稿；收到新的草稿帧或最终结果后会自动更新。'
}

function applyRealtimeJobEvent(jobId, event) {
  if (job.value?.id !== jobId) return
  const payload = event?.data?.payload || {}
  const nextJob = mergeMindmapAiJobEventSnapshot(job.value, event)
  if (nextJob !== job.value) {
    job.value = nextJob
    upsertSessionTurn(job.value)
    persistActiveJob()
  }
  if (event?.eventType === 'generation_restarted') markGenerationRestarted()
  if (
    ['artifact_ready', 'artifact_needs_review', 'artifact_no_change'].includes(event?.eventType)
    || isTerminalStatus(payload.status)
  ) schedulePoll(0, true)
}

function agentStatusText(agent) {
  if (agent.status === 'enabled' && !agentSupportsCurrentTask(agent)) return '不支持当前任务或来源'
  if (agent.status === 'enabled' && agent.healthStatus === 'healthy') return '连接正常'
  if (agent.status === 'enabled' && agent.healthStatus === 'unknown') return '首次运行时检查'
  if (agent.status === 'enabled') return agent.sdkName || '可用'
  return agent.statusReason || '当前不可用'
}

function currentSourceType() {
  if (form.sourceMode === 'new') return 'none'
  if (form.sourceMode === 'file') return 'uploaded_artifact'
  return editorContext.value?.mindmapId ? 'cloud_document' : 'local_snapshot'
}

function followupIntent(parentJob = followupParentJob.value) {
  if (parentJob?.status === 'needs_input') return parentJob.intent
  return effectiveFormIntent.value
}

function followupSourceType(parentJob = followupParentJob.value) {
  const sourceType = parentJob?.sourceType || currentSourceType()
  // A standalone generated artifact becomes the concrete input for its next
  // turn. Advertising it as `none` would incorrectly exclude Agents that can
  // continue from documents but cannot create from an empty source.
  if (parentJob?.artifactId && ['none', 'uploaded_artifact'].includes(sourceType)) {
    return 'uploaded_artifact'
  }
  return sourceType
}

function followupContinuationBase(parentJob = followupParentJob.value) {
  if (!['applied', 'undone'].includes(parentJob?.status)) return 'artifact'
  if (parentJob?.sourceType === 'cloud_document') return 'current_document'
  if (parentJob?.sourceType === 'local_snapshot') return 'current_snapshot'
  return 'artifact'
}

function agentSupportsCurrentTask(agent) {
  const intents = Array.isArray(agent?.intents) ? agent.intents : []
  const inputTypes = Array.isArray(agent?.inputTypes) ? agent.inputTypes : []
  const requestedIntent = effectiveFormIntent.value
  const formTaskSupported = intents.includes(requestedIntent)
    && inputTypes.includes(currentSourceType())
  if (retryAvailable.value) {
    const intent = job.value?.intent || form.intent
    const sourceType = job.value?.sourceType || currentSourceType()
    return intents.includes(intent)
      && inputTypes.includes(sourceType)
  }
  if (!followupAvailable.value) return formTaskSupported
  const intent = followupIntent()
  const sourceType = followupSourceType()
  return intents.includes(intent)
    && inputTypes.includes(sourceType)
}

function reconcileAgentSelection() {
  const resolution = resolveMindmapAiAgentSelection({
    agents: agents.value,
    selectedAgentKey: form.agentKey,
    supportsAgent: agentSupportsCurrentTask,
  })
  if (!form.agentKey && resolution.agentKey) form.agentKey = resolution.agentKey
  if (resolution.selectedAgent) onAgentChange()
  return Boolean(
    resolution.selectedAgent?.status === 'enabled'
    && agentSupportsCurrentTask(resolution.selectedAgent)
  )
}

function changeTypeLabel(type) {
  return ({
    create_node: '新增',
    update_node: '修改',
    move_node: '移动',
    delete_subtree: '删除',
    set_document_meta: '文档设置',
  })[type] || '变化'
}

async function loadProposal() {
  if (!job.value?.proposalId) {
    proposalLoadGeneration += 1
    proposal.value = null
    proposalError.value = ''
    proposalLoading.value = false
    diffConfirmed.value = false
    return false
  }
  const jobId = job.value.id
  const proposalId = job.value.proposalId
  const generation = ++proposalLoadGeneration
  proposalLoading.value = true
  try {
    const response = await getMindmapAiProposal(proposalId)
    if (
      generation !== proposalLoadGeneration
      || job.value?.id !== jobId
      || job.value?.proposalId !== proposalId
    ) return false
    proposal.value = response.data
    proposalError.value = ''
    diffConfirmed.value = false
    return true
  } catch (error) {
    if (
      generation !== proposalLoadGeneration
      || isAbortError(error)
      || job.value?.id !== jobId
    ) return false
    proposal.value = null
    proposalError.value = formatMindmapAiError(error, '无法加载 AI 提案差异')
    return false
  } finally {
    if (generation === proposalLoadGeneration) proposalLoading.value = false
  }
}

async function reloadProposal() {
  return loadProposal()
}

function onIntentChange(intent) {
  if (intent !== 'create' && form.sourceMode === 'new') {
    form.sourceMode = 'current'
  }
  reconcileAgentSelection()
}

function onAgentChange() {
  form.maxNodes = Math.min(form.maxNodes, maxNodesCap.value)
  form.maxDepth = Math.min(form.maxDepth, maxDepthCap.value)
  if (form.agentKey !== 'native_mindmap') return
  const selectedModelAvailable = availableModels.value.some(model => model.modelId === form.modelId)
  if (!selectedModelAvailable) form.modelId = availableModels.value[0]?.modelId || null
}

function usePromptStarter(type) {
  const starters = {
    research: {
      intent: 'create',
      prompt: '调研一个主题并总结关键结论、核心概念、事实依据与后续行动。',
    },
    plan: {
      intent: 'create',
      prompt: '把一个项目拆解为目标、里程碑、具体任务、负责人建议、风险与验收标准。',
    },
    trends: {
      intent: 'create',
      prompt: '梳理一个领域的发展趋势，按驱动因素、代表方向、机会、风险与观察指标组织。',
    },
    optimize: {
      intent: editorContext.value ? 'reorganize' : 'create',
      prompt: '分析并优化当前思维导图：保留有效信息，改善层级、命名、一致性和可执行性。',
    },
  }
  const starter = starters[type]
  if (!starter) return
  form.intent = starter.intent
  form.prompt = starter.prompt
  form.sourceMode = editorContext.value ? 'current' : 'new'
  discussionMode.value = false
  onIntentChange(form.intent)
}

function setReasoningMode(mode) {
  if (taskConfigurationLocked.value) return
  if (mode === 'quick') {
    form.density = 'concise'
    form.maxNodes = Math.min(60, maxNodesCap.value)
    form.maxDepth = Math.min(5, maxDepthCap.value)
  } else if (mode === 'deep') {
    form.density = 'detailed'
    form.maxNodes = Math.min(240, maxNodesCap.value)
    form.maxDepth = Math.min(10, maxDepthCap.value)
  } else {
    form.density = 'standard'
    form.maxNodes = Math.min(100, maxNodesCap.value)
    form.maxDepth = Math.min(6, maxDepthCap.value)
  }
}

async function sendComposerMessage() {
  if (!composerCanSend.value) return
  if (!job.value) await submitJob()
  else if (retryAvailable.value) await retryJob()
  else if (followupAvailable.value) await continueJob()
}

function onComposerKeydown(event) {
  if (
    event?.key !== 'Enter'
    || event.shiftKey
    || event.isComposing
    || event.keyCode === 229
  ) return
  event.preventDefault()
  void sendComposerMessage()
}

async function requestEditorContext() {
  const context = await new Promise((resolve, reject) => {
    const handled = bus.emit('requestAiMindmapContext', { resolve, reject })
    if (!handled) reject(new Error('脑图编辑器尚未就绪'))
  })
  editorContext.value = context
  selectedNodeUids.value = Array.isArray(context?.selectedNodeUids)
    ? context.selectedNodeUids
    : []
  return context
}

function nodeUid(node) {
  return String(
    node?.getData?.('uid')
    || node?.nodeData?.data?.uid
    || node?.getData?.()?.uid
    || '',
  ).trim()
}

function onEditorNodeActive(_node, activeNodes) {
  if (!visible.value) return
  selectedNodeUids.value = Array.from(new Set(
    (Array.isArray(activeNodes) ? activeNodes : []).map(nodeUid).filter(Boolean),
  ))
  if (form.scopeType === 'branch' && selectedNodeUids.value.length !== 1 && !job.value) {
    form.scopeType = selectedNodeUids.value.length ? 'selectedNodes' : 'document'
  }
}

function selectComposerContext(type) {
  if (taskConfigurationLocked.value || actionBusy.value) return false
  if (type === 'file') {
    if (!contextAvailability.value.file) return false
    contextPickerVisible.value = false
    selectSourceFile()
    return true
  }
  if (type === 'new') {
    if (!contextAvailability.value.newDocument) return false
    form.sourceMode = 'new'
    form.scopeType = 'document'
  } else if (['document', 'branch', 'selectedNodes'].includes(type)) {
    if (!contextAvailability.value[type]) return false
    form.sourceMode = 'current'
    form.scopeType = type
  } else {
    return false
  }
  contextPickerVisible.value = false
  reconcileAgentSelection()
  return true
}

function parseMindmapFile(file) {
  return new Promise((resolve, reject) => {
    const handled = bus.emit('parseMindmapFile', file, { resolve, reject })
    if (!handled) reject(new Error('脑图文件解析器尚未就绪'))
  })
}

function selectSourceFile() {
  sourceFileInputRef.value?.click()
}

async function onSourceFileChange(event) {
  const input = event.target
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  parsingFile.value = true
  try {
    const parsed = await parseMindmapFile(file)
    const artifact = await buildMindmapAiArtifactFromDocument(parsed.document, {
      title: String(parsed.name || '导入的脑图').replace(/\.[^.]+$/, ''),
    })
    await validateMindmapAiArtifact(artifact)
    uploadedFileArtifact.value = artifact
    uploadedFileName.value = parsed.name
    sourceContext.value = { document: artifact.document, mindmapId: null }
    form.layout = normalizedSourceLayout(artifact.document)
    form.sourceMode = 'file'
    ElMessage.success('文件已解析并通过 AI 输入校验')
  } catch (error) {
    uploadedFileArtifact.value = null
    uploadedFileName.value = ''
    ElMessage.error(formatMindmapAiError(error, 'AI 输入文件解析失败'))
  } finally {
    parsingFile.value = false
  }
}

function persistActiveJob() {
  const ownerUserId = currentAiOwnerUserId()
  if (!job.value?.id || !ownerUserId) return false
  const storedJob = {
    ownerUserId,
    jobId: job.value.id,
    sourceMindmapId: sourceContext.value?.mindmapId || null,
    sourceDocumentId: sourceContext.value?.documentId || null,
    sourceType: job.value.sourceType || null,
    sourceRevision: sourceContext.value?.revision ?? null,
    sourceFingerprint: sourceFingerprint.value || '',
    configuration: cloneRuntimeValue(jobConfiguration.value || captureJobConfiguration()),
    savedAt: Date.now(),
  }
  if (isTerminalStatus(job.value.status)) {
    clearMindmapAiOwnerSessionItem(ACTIVE_JOB_STORAGE_KEY, ownerUserId)
    return writeMindmapAiOwnerSessionItem(
      RECENT_JOB_STORAGE_KEY,
      ownerUserId,
      JSON.stringify(storedJob),
    )
  }
  clearMindmapAiOwnerSessionItem(RECENT_JOB_STORAGE_KEY, ownerUserId)
  return writeMindmapAiOwnerSessionItem(
    ACTIVE_JOB_STORAGE_KEY,
    ownerUserId,
    JSON.stringify(storedJob),
  )
}

async function restoreSessionTimeline(sessionId, {
  expectedJobId = job.value?.id,
  recoveryGeneration = restoreGeneration,
} = {}) {
  if (!sessionId) return false
  const generation = ++timelineLoadGeneration
  timelineController?.abort()
  const controller = new AbortController()
  timelineController = controller
  timelineLoading.value = true
  timelineError.value = ''
  try {
    const response = await getMindmapAiSessionTimeline(sessionId, { signal: controller.signal })
    if (
      generation !== timelineLoadGeneration
      || recoveryGeneration !== restoreGeneration
      || job.value?.id !== expectedJobId
      || job.value?.sessionId !== sessionId
    ) return false
    const turns = Array.isArray(response.data?.turns) ? response.data.turns : []
    currentSessionTitle.value = resolveMindmapAiSessionTitle(response.data?.title, turns)
    sessionTurns.value = turns
      .filter(turn => turn?.job?.id)
      .map(turn => cloneRuntimeValue(turn))
      .sort((left, right) => Number(left.job?.turnIndex || 0) - Number(right.job?.turnIndex || 0))
    let restoredCurrentJob = job.value
    const currentTurnJob = turns.find(turn => String(turn?.job?.id || '') === String(expectedJobId || ''))?.job
    if (currentTurnJob) {
      restoredCurrentJob = mergeMindmapAiJobSnapshot(restoredCurrentJob, currentTurnJob)
    }
    for (const turn of turns) {
      const turnJobId = String(turn?.job?.id || '')
      if (!turnJobId) continue
      if (turn.userMessage?.content) {
        appendClientPrompt(
          turnJobId,
          turn.userMessage.content,
          turn.job?.turnIndex || 1,
          turn.userMessage.createdTime,
        )
      }
      for (const event of Array.isArray(turn.events) ? turn.events : []) {
        const normalizedEvent = {
          eventType: event.eventType,
          data: {
            sequence: event.sequence,
            eventType: event.eventType,
            payload: event.payload,
            createdTime: event.createdTime,
          },
        }
        appendAgentEvent(turnJobId, normalizedEvent)
        if (turnJobId === String(expectedJobId || '')) {
          restoredCurrentJob = mergeMindmapAiJobEventSnapshot(restoredCurrentJob, normalizedEvent)
        }
      }
    }
    if (restoredCurrentJob !== job.value) {
      job.value = restoredCurrentJob
      upsertSessionTurn(job.value)
      persistActiveJob()
    }
    if (!selectedTurnJobId.value || !sessionTurns.value.some(turn => (
      String(turn.job?.id) === selectedTurnJobId.value
    ))) selectedTurnJobId.value = String(expectedJobId || '')
    syncCurrentJobCursor(expectedJobId)
    return sessionTurns.value
  } catch (error) {
    if (
      !isAbortError(error)
      && generation === timelineLoadGeneration
      && recoveryGeneration === restoreGeneration
      && job.value?.id === expectedJobId
    ) {
      timelineError.value = formatMindmapAiError(error, '无法恢复完整会话记录')
    }
    return false
  } finally {
    if (timelineController === controller) timelineController = null
    if (generation === timelineLoadGeneration) timelineLoading.value = false
  }
}

function latestSessionTurn() {
  return [...sessionTurns.value]
    .sort((left, right) => Number(right?.job?.turnIndex || 0) - Number(left?.job?.turnIndex || 0))[0]
    || null
}

function upsertSessionTurn(jobSnapshot, prompt = '') {
  if (!jobSnapshot?.id) return
  const existing = sessionTurns.value.find(turn => turn.job?.id === jobSnapshot.id)
  const nextTurn = {
    ...(existing || {}),
    job: cloneRuntimeValue(jobSnapshot),
    userMessage: existing?.userMessage || (prompt ? {
      content: prompt,
      createdTime: new Date().toISOString(),
    } : null),
    events: existing?.events || [],
  }
  sessionTurns.value = [
    ...sessionTurns.value.filter(turn => turn.job?.id !== jobSnapshot.id),
    nextTurn,
  ].sort((left, right) => Number(left.job?.turnIndex || 0) - Number(right.job?.turnIndex || 0))
}

async function selectSessionTurn(turn) {
  const turnJob = turn?.job
  if (!turnJob?.artifactId || actionBusy.value) return false
  const targetJobId = String(turnJob.id)
  const targetArtifactId = String(turnJob.artifactId)
  selectedTurnJobId.value = targetJobId
  selectedArtifactLoading.value = true
  terminalHydrationError.value = ''
  try {
    const { document } = await loadArtifact({
      requirePassed: false,
      artifactId: targetArtifactId,
    })
    if (
      selectedTurnJobId.value !== targetJobId
      || selectedArtifactJob.value?.artifactId !== targetArtifactId
    ) return false
    draftDocument.value = cloneRuntimeValue(document)
    latestPreviewVersion.value = -1
    return true
  } catch (error) {
    if (selectedTurnJobId.value === targetJobId) {
      terminalHydrationError.value = formatMindmapAiError(error, '历史轮次结果暂时无法加载')
    }
    return false
  } finally {
    if (selectedTurnJobId.value === targetJobId) selectedArtifactLoading.value = false
  }
}

function selectCurrentLiveTurn() {
  if (!job.value?.id) return
  selectedTurnJobId.value = String(job.value.id)
  draftDocument.value = null
  latestPreviewVersion.value = -1
  void refreshDraftPreview(job.value.id)
}

async function refreshTimelineAfterSideEffect(identity) {
  if (!actionIdentityMatches(identity) || !job.value?.sessionId) return false
  const loaded = await restoreSessionTimeline(job.value.sessionId, {
    expectedJobId: identity.jobId,
    recoveryGeneration: restoreGeneration,
  })
  assertActionIdentity(identity)
  return Boolean(loaded)
}

async function reconcileJobAfterSideEffect(identity) {
  // Job status alone cannot prove that the initiating editor loaded the
  // committed document. Settle any durable cloud intent first; this remains
  // safe even when the dialog action identity was invalidated by close.
  await flushPendingCloudMutationIntents()
  if (!actionIdentityMatches(identity) || !identity.jobId) return null
  try {
    const response = await getMindmapAiJob(identity.jobId)
    assertActionIdentity(identity)
    job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
    upsertSessionTurn(job.value)
    persistActiveJob()
    await refreshTimelineAfterSideEffect(identity)
    return job.value
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return null
    return null
  }
}

async function refreshAuthoritativeCloudMutationJob(identity, allowedStatuses) {
  const response = await getMindmapAiJob(identity.jobId)
  assertActionIdentity(identity)
  const authoritativeJob = mergeMindmapAiJobSnapshot(job.value, response.data)
  if (!allowedStatuses.includes(authoritativeJob?.status)) {
    throw createCloudMutationStateError('云端 AI 操作后的任务状态尚未完成同步，请稍后重试')
  }
  job.value = authoritativeJob
  return authoritativeJob
}

function assertFollowupAttemptResult(candidate, attempt, expectedSessionId = '') {
  const parentJobId = String(attempt?.parentJobId || '')
  const candidateId = String(candidate?.id || '')
  const candidateParentId = String(candidate?.parentJobId || '')
  const candidateSessionId = String(candidate?.sessionId || '')
  const knownJobIds = new Set(
    (Array.isArray(attempt?.knownJobIds) ? attempt.knownJobIds : []).map(String),
  )
  const knownMaxTurnIndex = Number(attempt?.knownMaxTurnIndex ?? attempt?.parentTurnIndex ?? 0)
  if (
    !attempt?.key
    || !parentJobId
    || !attempt?.requestPayload?.prompt
    || !candidateId
    || candidateParentId !== parentJobId
    || (expectedSessionId && candidateSessionId !== String(expectedSessionId))
    || (Number.isFinite(knownMaxTurnIndex)
      && Number(candidate?.turnIndex || 0) <= knownMaxTurnIndex)
    || knownJobIds.has(candidateId)
  ) throw new Error('继续生成对账结果与原请求身份不一致，已保留请求标识')
  return candidate
}

function assertRetryAttemptResult(candidate, attempt, expectedSessionId = '') {
  const retryOfJobId = String(attempt?.retryOfJobId || '')
  const candidateId = String(candidate?.id || '')
  const candidateRetryOfJobId = String(candidate?.retryOfJobId || '')
  const candidateParentJobId = String(candidate?.parentJobId || '')
  const candidateSessionId = String(candidate?.sessionId || '')
  const knownJobIds = new Set(
    (Array.isArray(attempt?.knownJobIds) ? attempt.knownJobIds : []).map(String),
  )
  const knownMaxTurnIndex = Number(attempt?.knownMaxTurnIndex ?? 0)
  if (
    !attempt?.key
    || !retryOfJobId
    || !candidateId
    || candidateRetryOfJobId !== retryOfJobId
    || candidateParentJobId
    || (expectedSessionId && candidateSessionId !== String(expectedSessionId))
    || (Number.isFinite(knownMaxTurnIndex)
      && Number(candidate?.turnIndex || 0) <= knownMaxTurnIndex)
    || knownJobIds.has(candidateId)
  ) throw new Error('重试任务对账结果与原请求身份不一致，已保留请求标识')
  return candidate
}

async function replayFollowupAttempt(attempt, expectedSessionId, { signal } = {}) {
  if (!attempt?.key || !attempt?.parentJobId || !attempt?.requestPayload) return null
  try {
    const reconciled = await reconcileMindmapAiJob(attempt.key, { signal })
    return assertFollowupAttemptResult(reconciled.data, attempt, expectedSessionId)
  } catch (error) {
    if (!isHttpNotFound(error)) throw error
  }
  // A persisted local-snapshot attempt intentionally omits the full document
  // from localStorage. In the original page lifetime the in-memory attempt is
  // still complete and can be retried exactly; after a reload, a confirmed
  // 404 leaves the marker in place until the user submits a fresh snapshot.
  if (
    attempt.requestPayload.continuationBase === 'current_snapshot'
    && !attempt.requestPayload.source?.document
  ) return null
  const replayed = await continueMindmapAiJob(
    attempt.parentJobId,
    attempt.requestPayload,
    attempt.key,
    { signal },
  )
  return assertFollowupAttemptResult(replayed.data, attempt, expectedSessionId)
}

async function replayRetryAttempt(attempt, expectedSessionId, { signal } = {}) {
  if (!attempt?.key || !attempt?.retryOfJobId || !attempt?.requestPayload) return null
  const response = await retryMindmapAiJob(
    attempt.retryOfJobId,
    attempt.requestPayload,
    attempt.key,
    { signal },
  )
  return assertRetryAttemptResult(response.data, attempt, expectedSessionId)
}

function retrySessionTimeline() {
  if (!job.value?.sessionId) return Promise.resolve(false)
  // A bare timeline reload cannot make a newly-created running child current.
  // Re-run the complete durable recovery: pending follow-ups are reconciled by
  // their exact idempotency key, and otherwise the authoritative latest turn is
  // promoted and monitored.
  persistActiveJob()
  invalidateRestoreOperations()
  return restoreActiveJob({ generation: restoreGeneration, allowRecent: true })
}

function invalidateSessionList() {
  sessionListGeneration += 1
  sessionListController?.abort()
  sessionListController = null
  sessionListLoading.value = false
}

async function loadRecentSessions() {
  if (!visible.value || sessionListLoading.value) return false
  const generation = ++sessionListGeneration
  sessionListController?.abort()
  const controller = new AbortController()
  sessionListController = controller
  sessionListLoading.value = true
  sessionListError.value = ''
  try {
    const response = await listMindmapAiSessions({ limit: 20, signal: controller.signal })
    if (
      generation !== sessionListGeneration
      || sessionListController !== controller
      || !visible.value
    ) return false
    recentSessions.value = normalizeMindmapAiSessionList(response.data).items
    return true
  } catch (error) {
    if (!isAbortError(error) && generation === sessionListGeneration) {
      sessionListError.value = formatMindmapAiError(error, '最近对话暂时无法加载')
    }
    return false
  } finally {
    if (sessionListController === controller) sessionListController = null
    if (generation === sessionListGeneration) sessionListLoading.value = false
  }
}

function sessionPointer(session) {
  const sessionJob = session?.currentJob || {}
  const sourceType = sessionJob.sourceType || null
  return {
    ownerUserId: currentAiOwnerUserId(),
    jobId: sessionJob.id,
    sourceMindmapId: sessionJob.sourceMindmapId || null,
    sourceDocumentId: null,
    sourceType,
    sourceRevision: sessionJob.baseRevision ?? null,
    sourceFingerprint: sessionJob.baseHash || '',
    configuration: {
      agentKey: sessionJob.agentKey,
      modelId: sessionJob.modelRef || null,
      intent: sessionJob.intent === 'discuss' ? 'create' : sessionJob.intent,
      sourceMode: sourceType === 'none'
        ? 'new'
        : sourceType === 'uploaded_artifact' ? 'file' : 'current',
      scopeType: 'document',
      language: 'zh-CN',
      layout: 'logicalStructure',
      density: 'standard',
      maxNodes: sessionJob.maxNodes,
      maxDepth: sessionJob.maxDepth,
      interactionMode: isMindmapAiMessageJob(sessionJob) ? 'discussion' : 'edit',
    },
    savedAt: Date.now(),
  }
}

async function switchToSession(session) {
  if (actionBusy.value || running.value || sessionUnavailableReason(session)) return false
  if (session.sessionId === job.value?.sessionId) {
    sessionMenuVisible.value = false
    return true
  }
  const pointer = sessionPointer(session)
  if (!pointer.ownerUserId || !pointer.jobId) return false
  sessionSwitching.value = true
  sessionMenuVisible.value = false
  resetNewJob({ clearStoredJob: false, preserveForm: true })
  const generation = restoreGeneration
  clearStoredActiveJob()
  clearStoredRecentJob()
  const storageKey = isTerminalStatus(session.currentJob?.status)
    ? RECENT_JOB_STORAGE_KEY
    : ACTIVE_JOB_STORAGE_KEY
  const stored = writeMindmapAiOwnerSessionItem(
    storageKey,
    pointer.ownerUserId,
    JSON.stringify(pointer),
  )
  if (!stored) {
    sessionSwitching.value = false
    restoreError.value = '浏览器无法保存所选会话的恢复指针。'
    return false
  }
  currentSessionTitle.value = session.title
  try {
    const restored = await restoreActiveJob({ generation, allowRecent: true })
    if (!restored && generation === restoreGeneration && !restoreError.value) {
      restoreError.value = '所选会话暂时无法恢复，请重试。'
    }
    return restored
  } finally {
    if (generation === restoreGeneration) sessionSwitching.value = false
  }
}

async function restoreActiveJob({
  generation = restoreGeneration,
  allowRecent = true,
} = {}) {
  let saved
  let controller = null
  let createAttempt = null
  let reconcilingCreateAttempt = false
  let reconciledFollowupAttemptKey = ''
  let reconciledRetryAttemptKey = ''
  try {
    const ownerUserId = currentAiOwnerUserId()
    const active = JSON.parse(
      readMindmapAiOwnerSessionItem(ACTIVE_JOB_STORAGE_KEY, ownerUserId) || 'null',
    )
    const recent = JSON.parse(
      readMindmapAiOwnerSessionItem(RECENT_JOB_STORAGE_KEY, ownerUserId) || 'null',
    )
    const isUsableStoredJob = candidate => Boolean(
      candidate?.jobId
      && ownerUserId
      && candidate.ownerUserId === ownerUserId
      && Number.isFinite(Number(candidate.savedAt))
      && Date.now() - Number(candidate.savedAt) <= STORED_JOB_TTL_MS
    )
    const activeUsable = isUsableStoredJob(active)
    const recentUsable = isUsableStoredJob(recent)
    if (active?.jobId && !activeUsable) clearStoredActiveJob()
    if (recent?.jobId && !recentUsable) clearStoredRecentJob()
    saved = activeUsable ? active : (allowRecent && recentUsable ? recent : null)
    if (!saved) {
      const persistedAttempts = readPersistedAttempts()
      createAttempt = persistedAttempts.create
      if (createAttempt?.key) {
        reconcilingCreateAttempt = true
        saved = {
          ...cloneRuntimeValue(createAttempt),
          jobId: null,
        }
      } else if (persistedAttempts.retry?.key && persistedAttempts.retry?.retryOfJobId) {
        // The durable retry marker is written before the request. It can
        // recover even if a separate active/recent pointer was unavailable.
        saved = {
          ...cloneRuntimeValue(persistedAttempts.retry),
          jobId: persistedAttempts.retry.retryOfJobId,
        }
      } else {
        return false
      }
    }
    if (
      saved.sourceMindmapId
      && Number(editorContext.value?.mindmapId) !== Number(saved.sourceMindmapId)
    ) return false
    if (
      saved.sourceDocumentId
      && editorContext.value?.documentId
      && editorContext.value.documentId !== saved.sourceDocumentId
    ) return false
    restoreController?.abort()
    controller = new AbortController()
    restoreController = controller
    restoringJob.value = true
    restoreError.value = ''
    // 本地撤销/应用是编辑器已经完成、服务端状态待确认的权威事实。必须先补发
    // 回执，再读取任务，避免基于过期的 ready 快照重复应用。
    await flushLocalApplyAcks()
    if (
      !componentAlive
      || generation !== restoreGeneration
      || restoreController !== controller
    ) return false
    let response
    if (reconcilingCreateAttempt) {
      try {
        response = await reconcileMindmapAiJob(createAttempt.key, { signal: controller.signal })
      } catch (error) {
        if (
          !componentAlive
          || generation !== restoreGeneration
          || restoreController !== controller
        ) return false
        // 404 是“该 key 尚未创建任务”，不是恢复故障。保留 attempt，用户再次提交
        // 相同 payload 时会复用同一个 key；网络/服务暂错则进入显式重试入口。
        if (isHttpNotFound(error)) {
          restoreError.value = ''
          restoreDurableAttemptNotice()
          return false
        }
        throw error
      }
    } else {
      response = await getMindmapAiJob(saved.jobId, { signal: controller.signal })
    }
    if (
      !componentAlive
      || generation !== restoreGeneration
      || restoreController !== controller
    ) return false
    if (!response.data?.id) throw new Error('AI 任务恢复响应缺少任务标识')
    job.value = response.data
    if (reconcilingCreateAttempt) {
      saved = {
        ...saved,
        jobId: job.value.id,
        sourceType: saved.sourceType || job.value.sourceType || null,
        savedAt: Date.now(),
      }
      // 先写入标准 active/recent 指针，再继续请求时间线与草稿。即使后续资源
      // 水合暂时失败，下一次打开也能从 jobId 恢复，而不会重复创建。
      restoreJobSourceState(job.value, saved)
      if (!persistActiveJob()) throw new Error('浏览器无法保存 AI 任务恢复指针，请重试')
      clearDurableAttempt('create', createAttempt.key)
      restoreDurableAttemptNotice()
    }
    if (!reconcilingCreateAttempt) {
      const persistedFollowup = readPersistedAttempts().followup
      const followupBelongsToRestoredSession = Boolean(
        persistedFollowup?.key
        && (
          String(persistedFollowup.parentJobId || '') === String(job.value.id || '')
          || String(persistedFollowup.parentJobId || '') === String(job.value.parentJobId || '')
          || (
            persistedFollowup.sessionId
            && String(persistedFollowup.sessionId) === String(job.value.sessionId || '')
          )
        )
      )
      if (followupBelongsToRestoredSession) {
        const recoveredChild = await replayFollowupAttempt(
          persistedFollowup,
          persistedFollowup.sessionId || job.value.sessionId,
          { signal: controller.signal },
        )
        if (
          !componentAlive
          || generation !== restoreGeneration
          || restoreController !== controller
        ) return false
        if (recoveredChild) {
          job.value = recoveredChild
          reconciledFollowupAttemptKey = persistedFollowup.key
        }
      }
      const persistedRetry = readPersistedAttempts().retry
      const retryBelongsToRestoredSession = Boolean(
        persistedRetry?.key
        && persistedRetry?.retryOfJobId
        && (
          String(persistedRetry.retryOfJobId) === String(job.value.id || '')
          || (
            persistedRetry.sessionId
            && String(persistedRetry.sessionId) === String(job.value.sessionId || '')
          )
        )
      )
      if (retryBelongsToRestoredSession) {
        const recoveredRetry = await replayRetryAttempt(
          persistedRetry,
          persistedRetry.sessionId || job.value.sessionId,
          { signal: controller.signal },
        )
        if (
          !componentAlive
          || generation !== restoreGeneration
          || restoreController !== controller
        ) return false
        if (recoveredRetry) {
          job.value = recoveredRetry
          saved = {
            ...saved,
            sourceRevision: recoveredRetry.baseRevision ?? saved.sourceRevision,
            configuration: persistedRetry.configuration || saved.configuration,
          }
          reconciledRetryAttemptKey = persistedRetry.key
        }
      }
    }
    const initialJobId = job.value.id
    await restoreSessionTimeline(job.value.sessionId, {
      expectedJobId: job.value.id,
      recoveryGeneration: generation,
    })
    if (
      !componentAlive
      || generation !== restoreGeneration
      || restoreController !== controller
      || job.value?.id !== initialJobId
    ) return false
    const latestTurn = latestSessionTurn()
    if (latestTurn?.job?.id && latestTurn.job.id !== initialJobId) {
      const latestResponse = await getMindmapAiJob(latestTurn.job.id, { signal: controller.signal })
      if (
        !componentAlive
        || generation !== restoreGeneration
        || restoreController !== controller
      ) return false
      if (latestResponse.data?.sessionId !== response.data?.sessionId) return false
      job.value = latestResponse.data
    }
    if (job.value.status === 'completed_file') clearDurableAttempt('save')
    selectedTurnJobId.value = String(job.value.id)
    restoreJobSourceState(job.value, saved)
    if (!persistActiveJob() && (reconciledFollowupAttemptKey || reconciledRetryAttemptKey)) {
      throw new Error('浏览器无法保存新轮次任务恢复指针，请重试')
    }
    if (reconciledFollowupAttemptKey) {
      clearDurableAttempt('followup', reconciledFollowupAttemptKey)
      restoreDurableAttemptNotice()
    }
    if (reconciledRetryAttemptKey) {
      clearDurableAttempt('retry', reconciledRetryAttemptKey)
      restoreDurableAttemptNotice()
    }
    if (!isMindmapAiMessageJob(job.value) && job.value.proposalId) await loadProposal()
    if (
      !componentAlive
      || generation !== restoreGeneration
      || restoreController !== controller
      || !job.value?.id
    ) return false
    if (isTerminalStatus(job.value.status)) {
      realtimeConnectionState.value = 'completed'
      realtimeError.value = ''
      persistActiveJob()
      await hydrateTerminalResources(job.value.id, { recoveryGeneration: generation })
      if (
        !componentAlive
        || generation !== restoreGeneration
        || restoreController !== controller
        || !job.value?.id
      ) return false
    } else {
      beginJobMonitoring()
    }
    return true
  } catch (error) {
    if (
      !isAbortError(error)
      && componentAlive
      && generation === restoreGeneration
      && (saved?.jobId || reconcilingCreateAttempt)
    ) {
      restoreError.value = formatMindmapAiError(
        error,
        reconcilingCreateAttempt
          ? '暂时无法确认上次创建请求；请求标识已保留，请重试恢复'
          : '暂时无法恢复 AI 脑图任务；任务标识已保留，请重试',
      )
    }
    return false
  } finally {
    if (generation === restoreGeneration) restoringJob.value = false
    if (restoreController === controller) restoreController = null
  }
}

function retryStoredJobRecovery() {
  invalidateRestoreOperations()
  return restoreActiveJob({ generation: restoreGeneration })
}

function discardStoredJobRecovery() {
  resetNewJob({ clearStoredJob: true, preserveForm: true })
  applyDialogPreset(pendingDialogPreset)
  pendingDialogPreset = null
  reconcileAgentSelection()
}

function onDialogClosed() {
  // 关闭也必须让“读取编辑器上下文 / 加载能力 / 恢复任务”整条异步链失效。
  // 否则用户在能力请求尚未返回时关闭弹窗，请求返回后仍可能在后台恢复并启动轮询。
  invalidateRestoreOperations({ clearError: false })
  invalidateSessionList()
  invalidateActionIdentity()
  mobilePreviewVisible.value = false
}

function startNewJob() {
  resetNewJob({ clearStoredJob: true, preserveForm: true })
  form.prompt = ''
  discussionMode.value = false
  showAdvancedSettings.value = false
  applyDialogPreset(pendingDialogPreset)
  pendingDialogPreset = null
  reconcileAgentSelection()
}

async function loadCapabilities({ recoveryGeneration = restoreGeneration } = {}) {
  loadingAgents.value = true
  agentError.value = ''
  try {
    const [agentResponse, modelResponse] = await Promise.all([
      listMindmapAiAgents(),
      listModelAll().catch(() => ({ data: [] })),
    ])
    if (recoveryGeneration !== restoreGeneration) return false
    agents.value = Array.isArray(agentResponse.data) ? agentResponse.data : []
    models.value = (Array.isArray(modelResponse.data) ? modelResponse.data : [])
      .filter(model => String(model.status ?? '0') === '0')
    reconcileAgentSelection()
    return true
  } catch (error) {
    if (recoveryGeneration === restoreGeneration) {
      agentError.value = formatMindmapAiError(error, '无法加载 AI Agent 能力清单')
    }
    return false
  } finally {
    if (recoveryGeneration === restoreGeneration) loadingAgents.value = false
  }
}

async function showDialog(preset = {}) {
  const explicitPreset = normalizeDialogPreset(preset)
  if (explicitPreset) pendingDialogPreset = explicitPreset
  visible.value = true
  resetNewJob({ clearStoredJob: false, preserveForm: true })
  const generation = restoreGeneration
  editorContext.value = null
  uploadedFileArtifact.value = null
  uploadedFileName.value = ''
  // Reconcile an irreversible cloud mutation before reading a new source
  // snapshot. This prevents a stale editor context from becoming the next AI
  // baseline after an apply/undo response or websocket broadcast was lost.
  await flushPendingCloudMutationIntents()
  if (generation !== restoreGeneration) return
  try {
    const context = await requestEditorContext()
    if (generation !== restoreGeneration) return
    await recoverLocalApplyAckFromContext(context)
    if (generation !== restoreGeneration) return
  } catch {
    selectedNodeUids.value = []
    form.sourceMode = 'new'
  }
  const restoredRecentDefaults = applyRecentJobDefaults(explicitPreset)
  applyDialogPreset(explicitPreset)
  if (!restoredRecentDefaults && !explicitPreset?.layout) {
    if (form.sourceMode === 'current') {
      form.layout = normalizedSourceLayout(editorContext.value?.document)
    } else if (form.sourceMode === 'file' && uploadedFileArtifact.value?.document) {
      form.layout = normalizedSourceLayout(uploadedFileArtifact.value.document)
    } else if (form.sourceMode === 'new') {
      form.layout = 'logicalStructure'
    }
  }
  await loadCapabilities({ recoveryGeneration: generation })
  if (generation !== restoreGeneration) return
  // A toolbar open may resume the recent terminal task. An explicit entry
  // point must instead honor its requested workflow. A genuinely
  // active/unknown create attempt still wins; the preset is retained and
  // applied when the user starts the next task.
  const restored = await restoreActiveJob({
    generation,
    allowRecent: !explicitPreset,
  })
  if (!restored) pendingDialogPreset = null
  if (!restored) restoreDurableAttemptNotice()
}

function buildScope() {
  if (form.scopeType === 'branch') {
    if (selectedNodeUids.value.length !== 1) {
      throw new Error('当前分支需要恰好选择一个节点')
    }
    const rootUid = selectedNodeUids.value[0]
    if (!rootUid) throw new Error('请先在画布中选择一个分支节点')
    return { type: 'branch', rootUid }
  }
  if (form.scopeType === 'selectedNodes') {
    if (selectedNodeUids.value.length === 0) throw new Error('请先在画布中选择节点')
    return { type: 'selectedNodes', nodeUids: [...selectedNodeUids.value] }
  }
  return { type: 'document' }
}

async function buildSource() {
  if (form.sourceMode === 'new') {
    sourceContext.value = null
    sourceFingerprint.value = ''
    return { type: 'none', scope: { type: 'document' } }
  }
  if (form.sourceMode === 'file') {
    if (!uploadedFileArtifact.value) throw new Error('请先选择并校验本地脑图文件')
    sourceContext.value = { document: uploadedFileArtifact.value.document, mindmapId: null }
    sourceFingerprint.value = uploadedFileArtifact.value.manifest.documentHash
    return {
      type: 'uploaded_artifact',
      artifact: uploadedFileArtifact.value,
      scope: { type: 'document' },
    }
  }
  let context = await requestEditorContext()
  context = await reconcileCloudMutationBeforeSource(context)
  const scope = buildScope()
  sourceContext.value = context
  sourceFingerprint.value = await computeMindmapSnapshotFingerprint(context.document)
  if (context.mindmapId) {
    return { type: 'cloud_document', mindmapId: context.mindmapId, scope }
  }
  return {
    type: 'local_snapshot',
    documentId: context.documentId,
    revision: context.revision,
    documentHash: sourceFingerprint.value,
    document: context.document,
    scope,
  }
}

function normalizedSourceLayout(document) {
  const layout = String(document?.layout || '')
  return AI_LAYOUT_VALUES.has(layout) ? layout : 'logicalStructure'
}

function effectiveRequestLayout(source) {
  if (source?.scope?.type && source.scope.type !== 'document') {
    return normalizedSourceLayout(sourceContext.value?.document || editorContext.value?.document)
  }
  return AI_LAYOUT_VALUES.has(form.layout) ? form.layout : 'logicalStructure'
}

function schedulePoll(delay = 900, force = false) {
  if (!componentAlive || !job.value?.id) return
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    realtimeConnectionState.value = 'offline'
    return
  }
  if (!force && isTerminalStatus(job.value.status)) return
  clearTimeout(pollTimer)
  const jobId = job.value.id
  pollTimer = setTimeout(() => {
    pollTimer = null
    void pollJob({ jobId, force })
  }, delay)
}

async function refreshDraftPreview(jobId) {
  if (!componentAlive || !jobId || job.value?.id !== jobId) return false
  if (isMindmapAiMessageJob(job.value)) return false
  if (selectedTurnJobId.value && selectedTurnJobId.value !== String(jobId)) return false
  draftController?.abort()
  const controller = new AbortController()
  draftController = controller
  try {
    const response = await getMindmapAiJobDraft(jobId, { signal: controller.signal })
    if (!componentAlive || job.value?.id !== jobId) return false
    return acceptDraftPreview(response.data)
  } catch (error) {
    if (!isAbortError(error) && job.value?.id === jobId) {
      realtimeError.value = formatMindmapAiError(error, '实时脑图草稿暂时不可用')
    }
    return false
  } finally {
    if (draftController === controller) draftController = null
  }
}

async function restoreTerminalPreview(jobId, {
  recoveryGeneration = restoreGeneration,
} = {}) {
  if (isMindmapAiMessageJob(job.value)) return false
  const displayCurrentJob = !selectedTurnJobId.value || selectedTurnJobId.value === String(jobId)
  const restoredDraft = await refreshDraftPreview(jobId)
  if (
    recoveryGeneration !== restoreGeneration
    || job.value?.id !== jobId
    || !job.value?.artifactId
  ) return restoredDraft
  const artifactId = job.value.artifactId
  try {
    const { document } = await loadArtifact({ requirePassed: false, artifactId })
    if (
      recoveryGeneration !== restoreGeneration
      || job.value?.id !== jobId
      || job.value?.artifactId !== artifactId
    ) return false
    if (displayCurrentJob && selectedTurnJobId.value === String(jobId)) {
      draftDocument.value = cloneRuntimeValue(document)
    }
    realtimeError.value = ''
    draftFreshness.value = 'final'
    draftFreshnessMessage.value = ''
    return Boolean(draftDocument.value?.root)
  } catch (error) {
    if (recoveryGeneration === restoreGeneration && job.value?.id === jobId) {
      realtimeError.value = formatMindmapAiError(error, 'AI 结果预览暂时无法恢复')
    }
    return false
  }
}

function scheduleTerminalHydrationRetry(jobId) {
  clearTimeout(terminalHydrationRetryTimer)
  terminalHydrationRetryTimer = null
  if (
    terminalHydrationRetryCount >= TERMINAL_HYDRATION_RETRY_DELAYS.length
    || !componentAlive
    || job.value?.id !== jobId
    || (typeof navigator !== 'undefined' && !navigator.onLine)
  ) return
  const delay = TERMINAL_HYDRATION_RETRY_DELAYS[terminalHydrationRetryCount]
  terminalHydrationRetryCount += 1
  terminalHydrationRetryTimer = setTimeout(() => {
    terminalHydrationRetryTimer = null
    schedulePoll(0, true)
  }, delay)
}

async function hydrateTerminalResources(jobId, {
  recoveryGeneration = restoreGeneration,
} = {}) {
  if (!jobId || job.value?.id !== jobId) return false
  terminalHydrationState.value = 'loading'
  terminalHydrationError.value = ''
  const messageJob = isMindmapAiMessageJob(job.value)
  const artifactReady = messageJob || !job.value.artifactId
    || await restoreTerminalPreview(jobId, { recoveryGeneration })
  if (recoveryGeneration !== restoreGeneration || job.value?.id !== jobId) return false
  const proposalReady = messageJob || !job.value.proposalId
    || proposal.value?.id === job.value.proposalId
    || await loadProposal()
  if (recoveryGeneration !== restoreGeneration || job.value?.id !== jobId) return false
  let needsInputReady = job.value.status !== 'needs_input' || needsInputQuestions.value.length > 0
  if (!needsInputReady && job.value.sessionId) {
    await restoreSessionTimeline(job.value.sessionId, {
      expectedJobId: jobId,
      recoveryGeneration,
    })
    if (recoveryGeneration !== restoreGeneration || job.value?.id !== jobId) return false
    needsInputReady = needsInputQuestions.value.length > 0
  }
  let assistantMessageReady = job.value.status !== 'completed_message'
    || Boolean(sessionTurns.value.find(turn => (
      String(turn?.job?.id || '') === String(jobId)
      && String(turn?.assistantMessage?.content || '').trim()
    )))
  if (!assistantMessageReady && job.value.sessionId) {
    await restoreSessionTimeline(job.value.sessionId, {
      expectedJobId: jobId,
      recoveryGeneration,
    })
    if (recoveryGeneration !== restoreGeneration || job.value?.id !== jobId) return false
    assistantMessageReady = Boolean(sessionTurns.value.find(turn => (
      String(turn?.job?.id || '') === String(jobId)
      && String(turn?.assistantMessage?.content || '').trim()
    )))
  }
  if (artifactReady && proposalReady && needsInputReady && assistantMessageReady) {
    terminalHydrationState.value = 'ready'
    terminalHydrationError.value = ''
    terminalHydrationRetryCount = 0
    clearTimeout(terminalHydrationRetryTimer)
    terminalHydrationRetryTimer = null
    return true
  }
  terminalHydrationState.value = 'error'
  terminalHydrationError.value = proposalError.value
    || timelineError.value
    || (job.value.status === 'needs_input' && !needsInputReady
      ? 'Agent 补充问题尚未完整同步，请重试加载。'
      : '')
    || (job.value.status === 'completed_message' && !assistantMessageReady
      ? 'AI 回答已经完成，但会话正文尚未完整同步。'
      : '')
    || realtimeError.value
    || 'AI 任务已完成，但结果资源尚未完整同步。'
  scheduleTerminalHydrationRetry(jobId)
  return false
}

function retryTerminalHydration() {
  if (!job.value?.id) return Promise.resolve(false)
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    terminalHydrationError.value = '当前处于离线状态；联网后会继续恢复结果。'
    return Promise.resolve(false)
  }
  terminalHydrationRetryCount = 0
  terminalHydrationError.value = ''
  schedulePoll(0, true)
  return Promise.resolve(true)
}

async function pollJob({ jobId = job.value?.id, force = false } = {}) {
  if (!componentAlive || !jobId || job.value?.id !== jobId) return
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    realtimeConnectionState.value = 'offline'
    return
  }
  if (!force && isTerminalStatus(job.value.status)) return
  pollController?.abort()
  const controller = new AbortController()
  pollController = controller
  try {
    const response = await getMindmapAiJob(jobId, { signal: controller.signal })
    if (!componentAlive || job.value?.id !== jobId) return
    job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
    // 权威轮询成功说明任务连接已经恢复。先清除旧 SSE 警告；若随后草稿
    // 拉取仍失败，refreshDraftPreview 会写入更准确的草稿错误。
    realtimeError.value = ''
    persistActiveJob()
    if (isTerminalStatus(job.value.status)) {
      await hydrateTerminalResources(jobId)
    } else if (!isMindmapAiMessageJob(job.value)) {
      await refreshDraftPreview(jobId)
    }
    if (!componentAlive || job.value?.id !== jobId) return
    if (
      !isMindmapAiMessageJob(job.value)
      && !isTerminalStatus(job.value.status)
      && job.value.proposalId
      && proposal.value?.id !== job.value.proposalId
    ) {
      await loadProposal()
    }
    if (isTerminalStatus(job.value.status)) {
      stopRealtime('completed')
      return
    }
    const delay = realtimeConnectionState.value === 'connected' ? 6000 : 1500
    schedulePoll(delay)
  } catch (error) {
    if (!isAbortError(error) && job.value?.id === jobId) {
      if (isTerminalStatus(job.value.status) || force) {
        terminalHydrationState.value = 'error'
        terminalHydrationError.value = formatMindmapAiError(
          error,
          '任务已完成，但结果状态暂时无法同步',
        )
        scheduleTerminalHydrationRetry(jobId)
        return
      }
      if (realtimeConnectionState.value !== 'connected') {
        realtimeError.value = formatMindmapAiError(error, 'AI 任务状态暂时无法同步')
      }
      schedulePoll(1800)
    }
  } finally {
    if (pollController === controller) pollController = null
  }
}

function scheduleRealtimeReconnect(jobId) {
  if (!componentAlive || job.value?.id !== jobId || isTerminalStatus(job.value?.status)) return
  clearTimeout(realtimeReconnectTimer)
  realtimeReconnectAttempt += 1
  const exponentialDelay = Math.min(
    REALTIME_RECONNECT_MAX_MS,
    REALTIME_RECONNECT_BASE_MS * (2 ** Math.min(realtimeReconnectAttempt - 1, 5)),
  )
  const jitteredDelay = Math.round(exponentialDelay * (0.85 + Math.random() * 0.3))
  realtimeConnectionState.value = navigator.onLine ? 'reconnecting' : 'offline'
  if (!navigator.onLine) return
  realtimeReconnectTimer = setTimeout(() => {
    realtimeReconnectTimer = null
    connectRealtime(jobId)
  }, jitteredDelay)
}

function connectRealtime(jobId) {
  if (!componentAlive || !jobId || job.value?.id !== jobId || isTerminalStatus(job.value.status)) return
  if (!navigator.onLine) {
    realtimeConnectionState.value = 'offline'
    scheduleRealtimeReconnect(jobId)
    return
  }
  clearTimeout(realtimeReconnectTimer)
  realtimeReconnectTimer = null
  const generation = ++realtimeGeneration
  realtimeController?.abort()
  const controller = new AbortController()
  realtimeController = controller
  realtimeConnectionState.value = 'connecting'

  void consumeMindmapAiRealtimeEvents(jobId, {
    afterSequence: latestEventSequence.value,
    previewVersion: latestPreviewVersion.value,
    signal: controller.signal,
    fetchDraft: getMindmapAiJobDraft,
    onOpen: () => {
      if (generation !== realtimeGeneration || job.value?.id !== jobId) return
      realtimeReconnectAttempt = 0
      realtimeConnectionState.value = 'connected'
      realtimeError.value = ''
    },
    onEvent: event => {
      if (generation !== realtimeGeneration || job.value?.id !== jobId) return
      if (event?.eventType === 'stream_error') {
        realtimeError.value = formatMindmapAiError(event?.data, '收到无效的 AI 实时事件')
      }
      if (appendAgentEvent(jobId, event)) applyRealtimeJobEvent(jobId, event)
    },
    onDraft: preview => {
      if (generation === realtimeGeneration && job.value?.id === jobId) {
        acceptDraftPreview(preview, { realtimeFrame: true })
      }
    },
    onDraftError: error => {
      if (generation !== realtimeGeneration || job.value?.id !== jobId || isAbortError(error)) return
      realtimeError.value = formatMindmapAiError(error, '实时脑图草稿暂时不可用')
      if (draftFreshness.value === 'restarted') {
        draftFreshnessMessage.value = draftDocument.value?.root
          ? '生成进程已重启；当前仍保留从持久检查点恢复的草稿。新草稿帧同步前，该画面不代表最新结果。'
          : '生成进程已重启，持久草稿暂时无法同步；最终结果就绪后会自动重新加载。'
      } else {
        draftFreshness.value = draftDocument.value?.root ? 'stale' : 'unavailable'
        draftFreshnessMessage.value = draftDocument.value?.root
          ? '实时草稿同步已中断；当前画面保留最后一次成功版本，恢复同步前请勿视为最新结果。'
          : '实时草稿同步已中断；最终结果就绪后会自动重新加载。'
      }
      schedulePoll(0)
    },
  }).then(cursor => {
    if (generation !== realtimeGeneration || job.value?.id !== jobId) return
    realtimeController = null
    latestEventSequence.value = Math.max(
      latestEventSequence.value,
      Number(cursor?.afterSequence) || 0,
    )
    jobEventSequences.set(jobId, latestEventSequence.value)
    latestPreviewVersion.value = Math.max(
      latestPreviewVersion.value,
      Number(cursor?.previewVersion) || -1,
    )
    if (isTerminalStatus(job.value.status)) {
      realtimeConnectionState.value = 'completed'
      realtimeError.value = ''
      return
    }
    schedulePoll(0)
    scheduleRealtimeReconnect(jobId)
  }).catch(error => {
    if (
      generation !== realtimeGeneration
      || job.value?.id !== jobId
      || isAbortError(error)
    ) return
    realtimeController = null
    realtimeError.value = formatMindmapAiError(error, 'AI 实时连接已中断，正在重连')
    schedulePoll(0)
    scheduleRealtimeReconnect(jobId)
  })
}

function beginJobMonitoring({ resetCursor = false } = {}) {
  const jobId = job.value?.id
  if (!jobId || isTerminalStatus(job.value.status)) return
  stopPolling()
  stopRealtime('idle')
  if (resetCursor) {
    resetCurrentJobCursor(jobId)
    latestPreviewVersion.value = -1
  } else {
    syncCurrentJobCursor(jobId)
  }
  if (hasUnresolvedGenerationRestart(jobId)) markGenerationRestarted()
  if (!isMindmapAiMessageJob(job.value)) void refreshDraftPreview(jobId)
  schedulePoll(0)
  connectRealtime(jobId)
}

async function submitJob() {
  if (restoringJob.value || actionBusy.value) return
  if (!form.prompt.trim()) return ElMessage.warning(messageModeActive.value ? '请输入想讨论的问题' : '请输入脑图生成要求')
  const requestedIntent = effectiveFormIntent.value
  if (!form.agentKey) return ElMessage.warning('没有可用的 AI Agent')
  const selectedAgent = agents.value.find(item => item.agentKey === form.agentKey)
  if (!selectedAgent || selectedAgent.status !== 'enabled') {
    return ElMessage.warning(selectedAgent?.statusReason || '所选 AI Agent 当前不可用')
  }
  if (!agentSupportsCurrentTask(selectedAgent)) {
    return ElMessage.warning('所选 AI Agent 不支持当前任务或输入来源')
  }
  if (form.agentKey === 'native_mindmap' && !form.modelId) {
    return ElMessage.warning('请选择自研 MindMap Agent 使用的模型')
  }
  submissionStartedAt.value = Date.now()
  submitting.value = true
  const identity = beginActionIdentity('create', { jobId: null })
  try {
    const source = await buildSource()
    assertActionIdentity(identity)
    const requestPayload = {
      agentKey: form.agentKey,
      modelId: form.agentKey === 'native_mindmap' ? form.modelId : undefined,
      intent: requestedIntent,
      prompt: form.prompt.trim(),
      parameters: {
        language: form.language,
        layout: effectiveRequestLayout(source),
        maxDepth: form.maxDepth,
        maxNodes: form.maxNodes,
        density: form.density,
      },
      source,
      target: discussionMode.value ? 'message' : (
        ['none', 'uploaded_artifact'].includes(source.type)
        || sourceContext.value?.readonly
      ) ? 'file' : 'proposal',
    }
    const requestConfiguration = captureJobConfiguration({
      agentKey: requestPayload.agentKey,
      modelId: requestPayload.modelId,
      // Preserve the selected editor intent while discussionMode controls the
      // actual request intent. This makes discussion -> edit deterministic.
      intent: form.intent,
      language: requestPayload.parameters.language,
      layout: requestPayload.parameters.layout,
      density: requestPayload.parameters.density,
      maxNodes: requestPayload.parameters.maxNodes,
      maxDepth: requestPayload.parameters.maxDepth,
      interactionMode: discussionMode.value ? 'discussion' : 'edit',
    })
    submitAttempt = await resolveDurableAttempt('create', submitAttempt, requestPayload, {
      createKey: () => createMindmapAiIdempotencyKey(),
      metadata: {
        sourceType: source.type,
        sourceDocumentId: sourceContext.value?.documentId || null,
        sourceMindmapId: sourceContext.value?.mindmapId || null,
        sourceRevision: sourceContext.value?.revision ?? null,
        sourceFingerprint: sourceFingerprint.value || '',
        configuration: requestConfiguration,
      },
    })
    assertActionIdentity(identity)
    const attemptKey = submitAttempt.key
    const response = await createMindmapAiJob(requestPayload, submitAttempt.key)
    assertActionIdentity(identity)
    submitAttempt = null
    stopPolling()
    stopRealtime('idle')
    clearAgentRuntimeState()
    job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
    identity.jobId = job.value.id
    discussionMode.value = isMindmapAiMessageJob(job.value)
    currentSessionTitle.value = deriveMindmapAiSessionTitle(requestPayload.prompt, '新对话')
    jobConfiguration.value = requestConfiguration
    appendClientPrompt(job.value.id, requestPayload.prompt, job.value.turnIndex)
    upsertSessionTurn(job.value, requestPayload.prompt)
    selectedTurnJobId.value = String(job.value.id)
    draftDocument.value = discussionMode.value
      ? null
      : cloneRuntimeValue(sourceContext.value?.document) || null
    proposal.value = null
    proposalError.value = ''
    diffConfirmed.value = false
    const pointerPersisted = persistActiveJob()
    if (pointerPersisted) {
      clearDurableAttempt('create', attemptKey)
    } else {
      restoreDurableAttemptNotice()
      ElMessage.warning('任务已创建；恢复指针未写入，请保持当前页面，原请求号仍可用于恢复')
    }
    beginJobMonitoring({ resetCursor: true })
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    ElMessage.error(formatMindmapAiError(error, 'AI 脑图任务创建失败'))
  } finally {
    submitting.value = false
    submissionStartedAt.value = 0
  }
}

async function activateFollowupJob(nextJob, {
  identity,
  requestPayload,
  attemptKey,
}) {
  assertActionIdentity(identity)
  const previousDraft = cloneRuntimeValue(draftDocument.value)
  stopPolling()
  stopRealtime('idle')
  job.value = nextJob
  identity.jobId = job.value.id
  const nextDiscussionMode = isMindmapAiMessageJob(job.value)
  const configuredEditIntent = intentOptions.some(item => (
    item.value === jobConfiguration.value?.intent
  )) ? jobConfiguration.value.intent : form.intent
  if (!nextDiscussionMode && intentOptions.some(item => item.value === job.value.intent)) {
    form.intent = job.value.intent
  }
  discussionMode.value = nextDiscussionMode
  const nextSourceMode = job.value.sourceType === 'none'
    ? 'new'
    : job.value.sourceType === 'uploaded_artifact' ? 'file' : 'current'
  form.sourceMode = nextSourceMode
  jobConfiguration.value = captureJobConfiguration({
    ...(jobConfiguration.value || {}),
    agentKey: requestPayload.agentKey,
    modelId: requestPayload.modelId,
    intent: nextDiscussionMode ? configuredEditIntent : form.intent,
    sourceMode: nextSourceMode,
    interactionMode: nextDiscussionMode ? 'discussion' : 'edit',
  })
  if (
    job.value.sourceType === 'uploaded_artifact'
    && previousDraft?.root
    && !sourceContext.value?.document?.root
  ) {
    sourceContext.value = {
      mindmapId: null,
      documentId: null,
      revision: job.value.baseRevision ?? null,
      document: previousDraft,
      readonly: false,
    }
  } else if (sourceContext.value && job.value.sourceType === 'cloud_document') {
    sourceContext.value = {
      ...sourceContext.value,
      revision: job.value.baseRevision ?? sourceContext.value.revision,
      document: null,
    }
  }
  sourceFingerprint.value = job.value.baseHash || ''
  appendClientPrompt(job.value.id, requestPayload.prompt, job.value.turnIndex)
  upsertSessionTurn(job.value, requestPayload.prompt)
  selectedTurnJobId.value = String(job.value.id)
  followupPrompt.value = ''
  proposal.value = null
  proposalError.value = ''
  diffConfirmed.value = false
  draftDocument.value = null
  const pointerPersisted = persistActiveJob()
  if (pointerPersisted) clearDurableAttempt('followup', attemptKey)
  followupAttempt = null
  restoreDurableAttemptNotice()
  await restoreSessionTimeline(job.value.sessionId, {
    expectedJobId: job.value.id,
    recoveryGeneration: restoreGeneration,
  })
  assertActionIdentity(identity)
  beginJobMonitoring({ resetCursor: true })
  if (!pointerPersisted) {
    ElMessage.warning('继续生成任务已创建；请保持当前页面，原请求号仍可用于恢复')
  }
  return true
}

async function activateRetryJob(nextJob, {
  identity,
  requestPayload,
  attemptKey,
  retryOfJob,
}) {
  assertActionIdentity(identity)
  stopPolling()
  stopRealtime('idle')
  job.value = nextJob
  identity.jobId = job.value.id
  discussionMode.value = isMindmapAiMessageJob(job.value)
  const nextConfiguration = captureJobConfiguration({
    ...(jobConfiguration.value || {}),
    agentKey: requestPayload.agentKey,
    modelId: requestPayload.modelId,
    maxNodes: nextJob.maxNodes ?? jobConfiguration.value?.maxNodes,
    maxDepth: nextJob.maxDepth ?? jobConfiguration.value?.maxDepth,
  })
  jobConfiguration.value = nextConfiguration
  if (sourceContext.value && nextJob.sourceType === 'cloud_document') {
    sourceContext.value = {
      ...sourceContext.value,
      revision: nextJob.baseRevision ?? sourceContext.value.revision,
      // The server refetched the cloud document. Do not present an older
      // editor snapshot as the new turn's authoritative draft.
      document: null,
    }
  }
  sourceFingerprint.value = nextJob.baseHash || ''
  const originalTurn = sessionTurns.value.find(turn => (
    String(turn?.job?.id || '') === String(retryOfJob?.id || '')
  ))
  const visiblePrompt = requestPayload.prompt
    || originalTurn?.userMessage?.content
    || '复用原任务要求'
  appendClientPrompt(job.value.id, visiblePrompt, job.value.turnIndex)
  upsertSessionTurn(job.value, visiblePrompt)
  selectedTurnJobId.value = String(job.value.id)
  retryPrompt.value = ''
  proposal.value = null
  proposalError.value = ''
  diffConfirmed.value = false
  draftDocument.value = null
  const pointerPersisted = persistActiveJob()
  if (pointerPersisted) clearDurableAttempt('retry', attemptKey)
  retryAttempt = null
  restoreDurableAttemptNotice()
  await restoreSessionTimeline(job.value.sessionId, {
    expectedJobId: job.value.id,
    recoveryGeneration: restoreGeneration,
  })
  assertActionIdentity(identity)
  beginJobMonitoring({ resetCursor: true })
  if (!pointerPersisted) {
    ElMessage.warning('重试任务已创建；请保持当前页面，原请求号仍可用于恢复')
  }
  return true
}

async function retryJob() {
  const retriedJob = job.value
  if (actionBusy.value || !retryAvailable.value || !retriedJob?.id) return
  const selectedAgent = agents.value.find(item => item.agentKey === form.agentKey)
  if (!selectedAgent || selectedAgent.status !== 'enabled') {
    return ElMessage.warning('请选择可用的 AI Agent 后再重试')
  }
  if (
    !selectedAgent.intents?.includes(retriedJob.intent)
    || !selectedAgent.inputTypes?.includes(retriedJob.sourceType)
  ) return ElMessage.warning('所选 AI Agent 不支持重试当前任务')
  if (form.agentKey === 'native_mindmap' && !form.modelId) {
    return ElMessage.warning('请选择自研 MindMap Agent 使用的模型')
  }
  retrying.value = true
  const identity = beginActionIdentity('retry', { jobId: retriedJob.id })
  let durableRetryAttempt = null
  try {
    const requestPayload = {
      agentKey: form.agentKey,
      modelId: form.agentKey === 'native_mindmap' ? form.modelId : undefined,
      prompt: retryPrompt.value.trim() || undefined,
      parameters: {
        language: jobConfiguration.value?.language || form.language,
        layout: jobConfiguration.value?.layout || form.layout,
      },
    }
    const knownMaxTurnIndex = Math.max(
      Number(retriedJob.turnIndex || 0),
      ...sessionTurns.value.map(turn => Number(turn?.job?.turnIndex || 0)),
    )
    retryAttempt = await resolveDurableAttempt(
      'retry',
      retryAttempt,
      { retryOfJobId: retriedJob.id, requestPayload },
      {
        createKey: () => createMindmapAiIdempotencyKey('mindmap-ai-retry'),
        metadata: {
          retryOfJobId: retriedJob.id,
          retryOfTurnIndex: retriedJob.turnIndex,
          sessionId: retriedJob.sessionId,
          sourceType: retriedJob.sourceType,
          sourceMindmapId: sourceContext.value?.mindmapId || retriedJob.sourceMindmapId || null,
          sourceDocumentId: sourceContext.value?.documentId || null,
          sourceRevision: retriedJob.baseRevision ?? sourceContext.value?.revision ?? null,
          sourceFingerprint: sourceFingerprint.value || '',
          knownMaxTurnIndex,
          knownJobIds: Array.from(new Set([
            String(retriedJob.id),
            ...sessionTurns.value.map(turn => String(turn?.job?.id || '')),
          ].filter(Boolean))),
          requestPayload,
          configuration: captureJobConfiguration({
            ...(jobConfiguration.value || {}),
            agentKey: requestPayload.agentKey,
            modelId: requestPayload.modelId,
          }),
        },
      },
    )
    durableRetryAttempt = readPersistedAttempts().retry
    assertActionIdentity(identity)
    const attemptKey = retryAttempt.key
    const response = await retryMindmapAiJob(
      retriedJob.id,
      requestPayload,
      retryAttempt.key,
    )
    assertActionIdentity(identity)
    const exactRetry = assertRetryAttemptResult(
      response.data,
      durableRetryAttempt,
      retriedJob.sessionId,
    )
    await activateRetryJob(exactRetry, {
      identity,
      requestPayload,
      attemptKey,
      retryOfJob: retriedJob,
    })
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    try {
      const recoveredRetry = await replayRetryAttempt(
        durableRetryAttempt,
        retriedJob.sessionId,
      )
      assertActionIdentity(identity)
      if (recoveredRetry) {
        await activateRetryJob(recoveredRetry, {
          identity,
          requestPayload: durableRetryAttempt.requestPayload,
          attemptKey: durableRetryAttempt.key,
          retryOfJob: retriedJob,
        })
        ElMessage.warning('重试请求已由原请求号精确恢复')
        return
      }
    } catch (recoveryError) {
      if (recoveryError?.code === 'AI_ACTION_SUPERSEDED') return
    }
    ElMessage.error(formatMindmapAiError(error, 'AI 脑图重试任务创建失败'))
  } finally {
    retrying.value = false
  }
}

async function continueJob() {
  const parentJob = followupParentJob.value
  if (
    actionBusy.value
    || !parentJob?.id
    || (
      !parentJob.artifactId
      && parentJob.status !== 'needs_input'
      && !(isMindmapAiMessageJob(parentJob) && parentJob.status === 'completed_message')
    )
    || !followupPrompt.value.trim()
  ) return
  const selectedAgent = agents.value.find(item => item.agentKey === form.agentKey)
  if (!selectedAgent || selectedAgent.status !== 'enabled') {
    return ElMessage.warning('请选择可用的 AI Agent 后再继续')
  }
  const requestedIntent = followupIntent(parentJob)
  const requestedSourceType = followupSourceType(parentJob)
  const continuationBase = followupContinuationBase(parentJob)
  if (
    !selectedAgent.intents?.includes(requestedIntent)
    || !selectedAgent.inputTypes?.includes(requestedSourceType)
  ) return ElMessage.warning('所选 AI Agent 不支持继续当前任务')
  if (form.agentKey === 'native_mindmap' && !form.modelId) {
    return ElMessage.warning('请选择自研 MindMap Agent 使用的模型')
  }
  continuing.value = true
  const identity = beginActionIdentity('followup', { jobId: job.value?.id })
  const parentTurnIndex = Number(parentJob.turnIndex || 0)
  let durableFollowupAttempt = null
  let currentSnapshotSource
  let expectedParentStatus
  try {
    const parentJobId = parentJob.id
    if (continuationBase === 'current_document') {
      await flushPendingCloudMutationIntents()
      assertActionIdentity(identity)
      const ownerUserId = currentAiOwnerUserId()
      const hasUnsettledMutation = ownerUserId
        && listMindmapAiCloudMutationIntents(ownerUserId).some(intent => (
          Number(intent.mindmapId) === Number(parentJob.sourceMindmapId)
        ))
      if (hasUnsettledMutation) {
        throw new Error('当前脑图仍有尚未完成的 AI 应用或撤销同步，请先完成恢复')
      }
      let currentContext = await requestEditorContext()
      assertActionIdentity(identity)
      currentContext = await reconcileCloudMutationBeforeSource(currentContext)
      assertActionIdentity(identity)
      if (Number(currentContext?.mindmapId) !== Number(parentJob.sourceMindmapId)) {
        throw new Error('当前打开的脑图不是继续调整的目标，请切回原脑图后重试')
      }
      sourceContext.value = currentContext
      editorContext.value = currentContext
      sourceFingerprint.value = await computeMindmapSnapshotFingerprint(currentContext.document)
      assertActionIdentity(identity)
    } else if (continuationBase === 'current_snapshot') {
      const ownerUserId = currentAiOwnerUserId()
      if (!ownerUserId || !parentJob.proposalId) {
        throw new Error('本地 AI 提案身份已丢失，请刷新后重试')
      }
      await flushLocalApplyAcks()
      assertActionIdentity(identity)
      const hasPendingReceipt = listMindmapAiLocalAcks(ownerUserId).some(receipt => (
        String(receipt.proposalId || '') === String(parentJob.proposalId)
      ))
      if (hasPendingReceipt) {
        throw new Error('本地 AI 应用或撤销回执尚未确认，请联网后重试')
      }
      const parentResponse = await getMindmapAiJob(parentJobId)
      assertActionIdentity(identity)
      const authoritativeParent = parentResponse.data
      if (
        authoritativeParent?.id !== parentJobId
        || authoritativeParent?.sessionId !== parentJob.sessionId
        || authoritativeParent?.sourceType !== 'local_snapshot'
        || !['applied', 'undone'].includes(authoritativeParent?.status)
      ) {
        throw new Error('本地 AI 任务状态已变化，请刷新后重试')
      }
      expectedParentStatus = authoritativeParent.status
      const currentContext = await requestEditorContext()
      assertActionIdentity(identity)
      if (
        currentContext?.mindmapId
        || !currentContext?.document?.root
        || !currentContext?.documentId
        || (
          sourceContext.value?.documentId
          && currentContext.documentId !== sourceContext.value.documentId
        )
        || !Number.isSafeInteger(Number(currentContext.revision))
      ) {
        throw new Error('当前打开的本地脑图不是继续调整的目标')
      }
      const currentHash = await computeMindmapSnapshotFingerprint(currentContext.document)
      assertActionIdentity(identity)
      if (currentContext.documentHash && currentContext.documentHash !== currentHash) {
        throw new Error('当前本地脑图快照在读取期间已变化，请重试')
      }
      const confirmedContext = await requestEditorContext()
      assertActionIdentity(identity)
      if (
        confirmedContext?.mindmapId
        || !confirmedContext?.document?.root
        || confirmedContext.documentId !== currentContext.documentId
        || Number(confirmedContext.revision) !== Number(currentContext.revision)
      ) {
        throw new Error('当前本地脑图快照在读取期间已变化，请重试')
      }
      const confirmedHash = await computeMindmapSnapshotFingerprint(confirmedContext.document)
      assertActionIdentity(identity)
      if (
        confirmedHash !== currentHash
        || (confirmedContext.documentHash && confirmedContext.documentHash !== confirmedHash)
      ) {
        throw new Error('当前本地脑图快照在读取期间已变化，请重试')
      }
      const stableContext = await requestEditorContext()
      assertActionIdentity(identity)
      if (
        stableContext?.mindmapId
        || stableContext?.documentId !== confirmedContext.documentId
        || Number(stableContext?.revision) !== Number(confirmedContext.revision)
        || (stableContext.documentHash && stableContext.documentHash !== confirmedHash)
      ) {
        throw new Error('当前本地脑图快照在读取期间已变化，请重试')
      }
      sourceContext.value = confirmedContext
      editorContext.value = confirmedContext
      sourceFingerprint.value = confirmedHash
      currentSnapshotSource = {
        type: 'local_snapshot',
        documentId: confirmedContext.documentId,
        revision: Number(confirmedContext.revision),
        documentHash: confirmedHash,
        document: confirmedContext.document,
        scope: { type: 'document' },
      }
    }
    const requestPayload = {
      prompt: followupPrompt.value.trim(),
      artifactId: continuationBase === 'artifact'
        ? (parentJob.artifactId || undefined)
        : undefined,
      agentKey: form.agentKey,
      modelId: form.agentKey === 'native_mindmap' ? form.modelId : undefined,
      intent: requestedIntent,
      continuationBase,
      expectedParentStatus: continuationBase === 'current_snapshot'
        ? expectedParentStatus
        : undefined,
      source: currentSnapshotSource,
    }
    const persistedRequestPayload = continuationBase === 'current_snapshot'
      ? { ...requestPayload, source: undefined }
      : requestPayload
    followupAttempt = await resolveDurableAttempt(
      'followup',
      followupAttempt,
      { parentJobId, requestPayload },
      {
        createKey: () => createMindmapAiIdempotencyKey('mindmap-ai-followup'),
        metadata: {
          parentJobId,
          parentTurnIndex,
          sessionId: parentJob.sessionId,
          knownMaxTurnIndex: Math.max(
            parentTurnIndex,
            ...sessionTurns.value.map(turn => Number(turn?.job?.turnIndex || 0)),
          ),
          knownJobIds: Array.from(new Set([
            String(job.value?.id || ''),
            ...sessionTurns.value.map(turn => String(turn?.job?.id || '')),
          ].filter(Boolean))),
          requestPayload: persistedRequestPayload,
        },
      },
    )
    const persistedFollowupAttempt = readPersistedAttempts().followup
    durableFollowupAttempt = persistedFollowupAttempt
      ? { ...persistedFollowupAttempt, requestPayload }
      : null
    assertActionIdentity(identity)
    const attemptKey = followupAttempt.key
    const response = await continueMindmapAiJob(
      parentJobId,
      requestPayload,
      followupAttempt.key,
    )
    assertActionIdentity(identity)
    const exactChild = assertFollowupAttemptResult(
      response.data,
      durableFollowupAttempt,
      parentJob.sessionId,
    )
    await activateFollowupJob(exactChild, {
      identity,
      requestPayload,
      attemptKey,
    })
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    try {
      const recoveredChild = await replayFollowupAttempt(
        durableFollowupAttempt,
        parentJob.sessionId,
      )
      assertActionIdentity(identity)
      if (recoveredChild) {
        await activateFollowupJob(recoveredChild, {
          identity,
          requestPayload: durableFollowupAttempt.requestPayload,
          attemptKey: durableFollowupAttempt.key,
        })
        ElMessage.warning('继续生成请求已由原请求号精确恢复')
        return
      }
    } catch (recoveryError) {
      if (recoveryError?.code === 'AI_ACTION_SUPERSEDED') return
    }
    ElMessage.error(formatMindmapAiError(error, '继续调整任务创建失败'))
  } finally {
    continuing.value = false
  }
}

async function loadArtifact({ requirePassed = true, artifactId = job.value?.artifactId } = {}) {
  if (!artifactId) throw new Error('AI 脑图结果尚未就绪')
  const blob = await downloadMindmapAiArtifact(artifactId)
  const artifact = JSON.parse(await blob.text())
  const validationStatus = artifact?.manifest?.validation?.status
  if (['passed', 'draft'].includes(validationStatus)) {
    artifactValidationStatuses.value = {
      ...artifactValidationStatuses.value,
      [String(artifactId)]: validationStatus,
    }
  }
  const checked = await assertMindmapAiArtifact(artifact, { requirePassed })
  await validateMindmapAiArtifact(artifact, requirePassed)
  return { blob, ...checked }
}

async function downloadArtifact() {
  downloading.value = true
  try {
    const artifactJob = selectedArtifactJob.value
    const artifactId = artifactJob?.artifactId
    const { blob } = await loadArtifact({ requirePassed: false, artifactId })
    const draftSuffix = isDraftArtifact(artifactId) ? '.draft' : ''
    saveAs(blob, `${artifactJob?.title || 'ai-mindmap'}${draftSuffix}.smm`)
  } catch (error) {
    ElMessage.error(formatMindmapAiError(error, 'AI 脑图文件下载失败'))
  } finally {
    downloading.value = false
  }
}

async function openArtifactAsLocal() {
  if (actionBusy.value) return
  const jobId = job.value?.id
  openingLocal.value = true
  const identity = beginActionIdentity('open-local', { jobId })
  try {
    await ElMessageBox.confirm(
      job.value.status === 'needs_review'
        ? '该草稿结果仍需要人工确认。将打开为新的本地脑图；当前本地工作区会保存到 7 天恢复记录中。'
        : '将 AI 结果打开为新的本地脑图。当前本地工作区会保存到 7 天恢复记录中。',
      '打开为本地脑图',
      { type: 'warning', confirmButtonText: '确认打开' },
    )
    assertActionIdentity(identity)
    const { document, documentHash } = await loadArtifact({ requirePassed: false })
    assertActionIdentity(identity)
    await emitEditorRequest('openAiArtifactAsLocal', { document, documentHash })
    assertActionIdentity(identity)
    if (editorContext.value?.mindmapId) {
      visible.value = false
      await router.push({ path: '/mindmap/edit', query: { localAi: Date.now() } })
    }
    ElMessage.success(
      job.value.status === 'needs_review'
        ? '草稿已打开，请检查并修正后再应用'
        : 'AI 结果已打开为本地脑图，可使用撤销恢复',
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    ElMessage.error(formatMindmapAiError(error, '打开本地脑图失败'))
  } finally {
    openingLocal.value = false
  }
}

async function replaceLocalWithArtifact() {
  if (actionBusy.value) return
  const identity = beginActionIdentity('replace-local', { jobId: job.value?.id })
  replacingLocal.value = true
  try {
    await ElMessageBox.confirm(
      '该操作会替换当前本地脑图，并合并为一条可撤销记录。',
      '替换当前本地脑图',
      { type: 'warning', confirmButtonText: '确认替换' },
    )
    assertActionIdentity(identity)
    const { document, documentHash } = await loadArtifact()
    assertActionIdentity(identity)
    await emitEditorRequest('replaceLocalWithAiArtifact', { document, documentHash })
    assertActionIdentity(identity)
    ElMessage.success('已替换当前本地脑图，可使用撤销恢复')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    ElMessage.error(formatMindmapAiError(error, '替换本地脑图失败'))
  } finally {
    replacingLocal.value = false
  }
}

async function insertArtifactBranch() {
  if (actionBusy.value) return
  const identity = beginActionIdentity('insert-local', { jobId: job.value?.id })
  insertingLocal.value = true
  try {
    const { document, documentHash } = await loadArtifact()
    assertActionIdentity(identity)
    await emitEditorRequest('insertAiArtifactBranch', { document, documentHash })
    assertActionIdentity(identity)
    ElMessage.success('AI 结果已作为一条可撤销变更插入')
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    ElMessage.error(formatMindmapAiError(error, '插入 AI 分支失败'))
  } finally {
    insertingLocal.value = false
  }
}

async function saveCloud() {
  if (actionBusy.value || !job.value?.id || !job.value?.artifactId) return
  const jobId = job.value.id
  const artifactId = job.value.artifactId
  savingCloud.value = true
  const identity = beginActionIdentity('save-cloud', { jobId, artifactId })
  try {
    const name = await ElMessageBox.prompt('请输入云端脑图名称', '另存云端', {
      inputValue: job.value.title || 'AI 脑图',
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
    })
    assertActionIdentity(identity)
    const requestPayload = {
      artifactId,
      name: name.value.trim(),
    }
    saveCloudAttempt = await resolveDurableAttempt('save', saveCloudAttempt, requestPayload, {
      createKey: () => createMindmapAiIdempotencyKey('mindmap-ai-save'),
      metadata: { jobId, requestPayload },
    })
    assertActionIdentity(identity)
    const attemptKey = saveCloudAttempt.key
    const response = await saveMindmapAiArtifactCloud(
      requestPayload.artifactId,
      { name: requestPayload.name },
      saveCloudAttempt.key,
    )
    assertActionIdentity(identity)
    clearDurableAttempt('save', attemptKey)
    saveCloudAttempt = null
    job.value = { ...job.value, status: 'completed_file', progress: 100 }
    upsertSessionTurn(job.value)
    persistActiveJob()
    await refreshTimelineAfterSideEffect(identity)
    ElMessage.success(`已保存为云端脑图 #${response.data.id}`)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    const reconciled = await reconcileJobAfterSideEffect(identity)
    if (reconciled?.status === 'completed_file') {
      clearDurableAttempt('save')
      saveCloudAttempt = null
      ElMessage.warning('另存请求已提交，已从服务端恢复结果')
      return
    }
    ElMessage.error(formatMindmapAiError(error, '另存云端失败'))
  } finally {
    savingCloud.value = false
  }
}

function emitEditorRequest(event, payload, options = {}) {
  return new Promise((resolve, reject) => {
    const handled = bus.emit(event, payload, { ...options, resolve, reject })
    if (!handled) reject(new Error('脑图编辑器尚未就绪'))
  })
}

function cloudMutationIdentity(intent) {
  return {
    ownerUserId: intent.ownerUserId,
    action: intent.action,
    proposalId: intent.proposalId,
    idempotencyKey: intent.idempotencyKey,
  }
}

function cloudMutationExecutionKey(intent) {
  return [intent.ownerUserId, intent.action, intent.proposalId, intent.idempotencyKey].join(':')
}

function createCloudMutationStateError(message, code = 'AI_CLOUD_RECONCILE_STATE_INVALID') {
  const error = new Error(message)
  error.code = code
  return error
}

function assertCloudMutationOwner(intent) {
  if (intent.ownerUserId === currentAiOwnerUserId()) return true
  const error = new Error('登录账号已变化，已保留原账号的云端 AI 操作恢复记录')
  error.code = 'AI_CLOUD_OWNER_CHANGED'
  throw error
}

function assertCloudMutationProposal(intent, candidate) {
  if (
    !candidate
    || String(candidate.id || '') !== String(intent.proposalId)
    || String(candidate.jobId || '') !== String(intent.jobId)
    || Number(candidate.targetMindmapId) !== Number(intent.mindmapId)
  ) {
    throw createCloudMutationStateError('云端 AI 操作的权威提案身份不一致，请人工核对脑图')
  }
  return candidate
}

function assertCloudMutationResponse(intent, candidate) {
  const revision = Number(candidate?.contentRevision)
  if (
    String(candidate?.proposalId || '') !== String(intent.proposalId)
    || candidate?.status !== intent.expectedStatus
    || !Number.isSafeInteger(revision)
    || revision < 1
  ) {
    throw createCloudMutationStateError('云端 AI 操作响应无法确认权威版本，请人工核对脑图')
  }
  return revision
}

function rememberPermanentCloudMutationFailure(intent, error) {
  const code = resolveMindmapAiErrorCode(error)
  if (!PERMANENT_CLOUD_MUTATION_CODES.has(code)) return false
  try {
    markMindmapAiCloudMutationFailed(cloudMutationIdentity(intent), code)
    updateCloudMutationRecoveryNotice([error])
  } catch {}
  return true
}

async function settleCloudMutationIntent(persistedIntent) {
  const identity = cloudMutationIdentity(persistedIntent)
  let intent = getMindmapAiCloudMutationIntent(identity)
  if (!intent) return { settled: true, intent: null }
  assertCloudMutationOwner(intent)
  if (intent.phase === 'permanent_failed') {
    throw createCloudMutationStateError(
      `云端 AI 操作已停止自动重试（错误码：${intent.errorCode}），请刷新后人工核对脑图`,
      intent.errorCode,
    )
  }

  try {
    if (intent.phase === 'pending_server') {
      // An unresolved request starts with an authoritative proposal GET. It
      // tells us whether the original request committed even when its HTTP
      // response was lost. Once a server receipt has been persisted, however,
      // proposal retention or a later permission change must not block the
      // already-required editor reload.
      const proposalResponse = await getMindmapAiProposal(intent.proposalId)
      assertCloudMutationOwner(intent)
      const authoritativeProposal = assertCloudMutationProposal(intent, proposalResponse.data)
      let confirmedRevision = null
      if (intent.action === 'apply' && authoritativeProposal.status === 'applied') {
        const appliedRevision = Number(authoritativeProposal.appliedRevision)
        if (Number.isSafeInteger(appliedRevision) && appliedRevision > 0) {
          confirmedRevision = appliedRevision
        }
      }
      const requestCanBeReplayed = intent.action === 'apply'
        ? ['ready', 'prepared', 'needs_review'].includes(authoritativeProposal.status)
        : ['applied', 'undone'].includes(authoritativeProposal.status)
      if (confirmedRevision === null && !requestCanBeReplayed) {
        throw createCloudMutationStateError(
          `云端 AI ${intent.action === 'undo' ? '撤销' : '应用'}已被后续状态取代，请人工核对脑图`,
          authoritativeProposal.status === 'stale' || authoritativeProposal.status === 'expired'
            ? 'AI_PROPOSAL_STALE'
            : 'AI_CLOUD_MUTATION_SUPERSEDED',
        )
      }
      if (confirmedRevision === null) {
        assertCloudMutationOwner(intent)
        const response = intent.action === 'apply'
          ? await applyMindmapAiCloudProposal(
              intent.mindmapId,
              intent.proposalId,
              intent.requestPayload,
              intent.idempotencyKey,
            )
          : await undoMindmapAiCloudProposal(
              intent.mindmapId,
              intent.proposalId,
              intent.idempotencyKey,
            )
        confirmedRevision = assertCloudMutationResponse(intent, response.data)
      }
      intent = markMindmapAiCloudMutationConfirmed(identity, confirmedRevision)
      if (!intent) throw new Error('云端 AI 操作恢复记录已经变化，请重试')
    }

    // The persisted server receipt is sufficient and must survive proposal
    // retention/permission changes. Reloading uses its revision as a floor and
    // therefore also picks up any legitimate later apply/undo.
    assertCloudMutationOwner(intent)
    const revision = Number(intent.confirmedContentRevision)
    const receipt = await emitEditorRequest('aiCloudProposalApplied', {
      mindmapId: intent.mindmapId,
      contentRevision: revision,
      forceOverwrite: intent.requestPayload?.forceOverwrite === true,
    })
    assertCloudMutationOwner(intent)
    if (
      Number(receipt?.mindmapId) !== Number(intent.mindmapId)
      || !Number.isSafeInteger(Number(receipt?.contentRevision))
      || Number(receipt.contentRevision) < revision
    ) {
      throw new Error('编辑器尚未确认云端 AI 操作的权威版本')
    }
    removeMindmapAiCloudMutationIntent(identity)
    updateCloudMutationRecoveryNotice()
    return { settled: true, intent, receipt }
  } catch (error) {
    rememberPermanentCloudMutationFailure(intent, error)
    throw error
  }
}

function executeCloudMutationIntent(intent) {
  const key = cloudMutationExecutionKey(intent)
  const activeExecution = cloudMutationExecutions.get(key)
  if (activeExecution) return activeExecution
  const operation = settleCloudMutationIntent(intent)
  cloudMutationExecutions.set(key, operation)
  void operation.finally(() => {
    if (cloudMutationExecutions.get(key) === operation) cloudMutationExecutions.delete(key)
  }).catch(() => {})
  return operation
}

async function executeCloudMutationWithRecovery(intent) {
  try {
    return await executeCloudMutationIntent(intent)
  } catch (firstError) {
    const persisted = getMindmapAiCloudMutationIntent(cloudMutationIdentity(intent))
    if (
      !persisted
      || persisted.phase === 'permanent_failed'
      || (typeof navigator !== 'undefined' && !navigator.onLine)
    ) throw firstError
    // One immediate exact replay closes the common "server committed but the
    // response was lost" window. Continued outages stay in the durable outbox
    // and resume on editor-ready, online, or the next dialog open.
    try {
      return await executeCloudMutationIntent(persisted)
    } catch (recoveryError) {
      throw recoveryError || firstError
    }
  }
}

function updateCloudMutationRecoveryNotice(failures = []) {
  const ownerUserId = currentAiOwnerUserId()
  const intents = ownerUserId
    ? listMindmapAiCloudMutationIntents(ownerUserId)
    : []
  const permanentFailure = intents.find(intent => intent.phase === 'permanent_failed')
  cloudMutationHasPermanentFailure.value = Boolean(permanentFailure)
  if (permanentFailure) {
    cloudMutationRetryable.value = intents.some(intent => intent.phase !== 'permanent_failed')
    cloudMutationRecoveryError.value = `云端 AI ${permanentFailure.action === 'undo' ? '撤销' : '应用'}无法自动恢复（错误码：${permanentFailure.errorCode}）。请刷新目标脑图并人工核对，系统已停止自动重试。`
    return
  }
  if (intents.length) {
    cloudMutationRetryable.value = true
    cloudMutationRecoveryError.value = failures.length
      ? '云端 AI 操作已保存恢复记录，但权威画布尚未同步；联网并打开目标脑图后重试。'
      : '检测到尚未完成权威画布同步的云端 AI 操作。'
    return
  }
  cloudMutationRetryable.value = false
  cloudMutationHasPermanentFailure.value = false
  cloudMutationRecoveryError.value = ''
}

function flushPendingCloudMutationIntents() {
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId) {
    updateCloudMutationRecoveryNotice()
    return Promise.resolve({ settled: [], failures: [] })
  }
  const activeFlush = cloudMutationFlushPromises.get(ownerUserId)
  if (activeFlush) return activeFlush
  const operation = (async () => {
    cloudMutationRecovering.value = true
    const failures = []
    const settled = []
    for (const intent of listMindmapAiCloudMutationIntents(ownerUserId)) {
      if (intent.phase === 'permanent_failed') continue
      try {
        await executeCloudMutationIntent(intent)
        settled.push(cloudMutationExecutionKey(intent))
      } catch (error) {
        failures.push(error)
      }
    }
    if (currentAiOwnerUserId() === ownerUserId) {
      updateCloudMutationRecoveryNotice(failures)
    }
    return { settled, failures }
  })()
  cloudMutationFlushPromises.set(ownerUserId, operation)
  void operation.finally(() => {
    if (cloudMutationFlushPromises.get(ownerUserId) === operation) {
      cloudMutationFlushPromises.delete(ownerUserId)
    }
    cloudMutationRecovering.value = cloudMutationFlushPromises.size > 0
  }).catch(() => {})
  return operation
}

async function retryCloudMutationRecovery() {
  const result = await flushPendingCloudMutationIntents()
  if (!result.failures.length && result.settled.length) {
    ElMessage.success('云端 AI 操作已与权威画布同步')
  }
  return result
}

async function discardPermanentCloudMutationRecovery() {
  const ownerUserId = currentAiOwnerUserId()
  const permanentIntents = ownerUserId
    ? listMindmapAiCloudMutationIntents(ownerUserId)
      .filter(intent => intent.phase === 'permanent_failed')
    : []
  if (!permanentIntents.length) {
    updateCloudMutationRecoveryNotice()
    return false
  }
  try {
    await ElMessageBox.confirm(
      `仅在你已刷新并人工核对目标脑图后继续。将清除 ${permanentIntents.length} 条无法自动恢复的本地对账记录，不会再次修改云端脑图。`,
      '清除云端 AI 操作恢复记录',
      { type: 'warning', confirmButtonText: '已核对，清除记录' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return false
    throw error
  }
  if (currentAiOwnerUserId() !== ownerUserId) return false
  try {
    for (const intent of permanentIntents) {
      removeMindmapAiCloudMutationIntent(cloudMutationIdentity(intent))
    }
  } catch (error) {
    ElMessage.error(formatMindmapAiError(error, '云端 AI 操作恢复记录清除失败'))
    return false
  }
  updateCloudMutationRecoveryNotice()
  ElMessage.success('已清除人工核对完成的云端 AI 操作恢复记录')
  return true
}

async function reconcileCloudMutationBeforeSource(context) {
  const ownerUserId = currentAiOwnerUserId()
  const mindmapId = Number(context?.mindmapId)
  if (!ownerUserId || !Number.isSafeInteger(mindmapId) || mindmapId < 1) return context
  const hasPendingForDocument = () => listMindmapAiCloudMutationIntents(ownerUserId)
    .some(intent => (
      intent.phase !== 'permanent_failed'
      && Number(intent.mindmapId) === mindmapId
    ))
  if (!hasPendingForDocument()) return context
  await flushPendingCloudMutationIntents()
  if (currentAiOwnerUserId() !== ownerUserId || hasPendingForDocument()) {
    throw new Error('当前脑图仍有尚未完成画布同步的云端 AI 操作，请先完成恢复再生成')
  }
  const refreshedContext = await requestEditorContext()
  if (Number(refreshedContext?.mindmapId) !== mindmapId) {
    throw new Error('云端 AI 操作恢复期间脑图上下文已变化，请重试')
  }
  return refreshedContext
}

async function onCloudMutationRecoveryReady() {
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId) return
  // The dialog can mount and start reconciliation before the editor finishes
  // binding its receipt handler. If editor-ready arrives while that first
  // attempt is still active, wait for it and then retry only when the same
  // owner's durable intent is still pending. This closes the lost wake-up
  // window without creating a retry loop for genuine network failures.
  const activeFlush = cloudMutationFlushPromises.get(ownerUserId)
  if (activeFlush) {
    try { await activeFlush } catch {}
  }
  if (
    !componentAlive
    || currentAiOwnerUserId() !== ownerUserId
    || !listMindmapAiCloudMutationIntents(ownerUserId)
      .some(intent => intent.phase !== 'permanent_failed')
  ) return
  await flushPendingCloudMutationIntents()
}

function onLocalAiJournalRecovered(payload = {}) {
  if (!componentAlive) return
  if (
    job.value?.proposalId
    && String(job.value.proposalId) === String(payload.proposalId || '')
  ) {
    schedulePoll(0, true)
    if (job.value.sessionId) {
      void restoreSessionTimeline(job.value.sessionId, {
        expectedJobId: job.value.id,
        recoveryGeneration: restoreGeneration,
      })
    }
  }
}

function clearLocalAckRetryTimer() {
  clearTimeout(localAckRetryTimer)
  localAckRetryTimer = null
}

function scheduleLocalAckRetry() {
  clearLocalAckRetryTimer()
  if (!componentAlive || (typeof navigator !== 'undefined' && !navigator.onLine)) return
  const pending = listMindmapAiLocalAcks(currentAiOwnerUserId())
  if (!pending.length) return
  const attempts = Math.max(0, ...pending.map(item => Number(item.attempts) || 0))
  const delay = Math.min(
    LOCAL_ACK_RETRY_BASE_MS * (2 ** Math.min(attempts, 10)),
    LOCAL_ACK_RETRY_MAX_MS,
  )
  localAckRetryTimer = setTimeout(() => {
    localAckRetryTimer = null
    void flushLocalApplyAcks()
  }, delay)
}

async function flushLocalApplyAcks() {
  clearLocalAckRetryTimer()
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId) return { sent: 0, pending: 0, discarded: 0 }
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    return {
      sent: 0,
      pending: listMindmapAiLocalAcks(ownerUserId).length,
      discarded: 0,
    }
  }
  const result = await flushMindmapAiLocalAcks(async (proposalId, payload, action) => {
    if (currentAiOwnerUserId() !== ownerUserId) {
      const error = new Error('登录账号已变化，本地 AI 回执将留待原账号恢复')
      error.code = 'AI_AUTH_REQUIRED'
      throw error
    }
    const response = action === 'undo'
      ? ackMindmapAiLocalUndo(proposalId, payload)
      : ackMindmapAiLocalApply(proposalId, payload)
    const resolved = await response
    confirmMindmapAiLocalJournalAck(
      ownerUserId,
      proposalId,
      payload,
      action || 'apply',
    )
    return resolved
  }, ownerUserId)
  if (!componentAlive || currentAiOwnerUserId() !== ownerUserId) return result
  if (result.sent > 0 && job.value?.id) {
    const expectedJobId = job.value.id
    schedulePoll(0, true)
    if (job.value.sessionId) {
      await restoreSessionTimeline(job.value.sessionId, {
        expectedJobId,
        recoveryGeneration: restoreGeneration,
      })
    }
  }
  if (result.discarded > 0) {
    const reason = result.discardedFailures?.[0]?.message
    ElMessage.warning(
      `${result.discarded} 条本地 AI 回执已被服务端拒绝，已停止自动重试。`
      + `${reason ? `原因：${reason}。` : ''}请人工确认任务与当前脑图状态。`,
    )
  }
  if (result.pending > 0) scheduleLocalAckRetry()
  return result
}

async function queueLocalAck(action, proposalId, payload) {
  const ownerUserId = currentAiOwnerUserId()
  const send = action === 'undo' ? ackMindmapAiLocalUndo : ackMindmapAiLocalApply
  try {
    enqueueMindmapAiLocalAck({
      ownerUserId,
      ...(action === 'undo' ? { action } : {}),
      proposalId,
      ...payload,
    })
  } catch (storageError) {
    // 本地操作已经原子落地；若浏览器无法持久化回执，先直接调用幂等接口，
    // 避免把一个实际不存在的队列误报成“联网后自动补发”。
    if (!ownerUserId || currentAiOwnerUserId() !== ownerUserId) {
      return { sent: 0, pending: 0, receiptUnstored: true, storageError }
    }
    try {
      await send(proposalId, payload)
      confirmMindmapAiLocalJournalAck(ownerUserId, proposalId, payload, action)
      return { sent: 1, pending: 0, storageFailed: true }
    } catch (sendError) {
      return {
        sent: 0,
        pending: 0,
        receiptUnstored: true,
        error: sendError,
        storageError,
      }
    }
  }
  return flushLocalApplyAcks()
}

function queueLocalApplyAck(proposalId, payload) {
  return queueLocalAck('apply', proposalId, payload)
}

function queueLocalUndoAck(proposalId, payload) {
  return queueLocalAck('undo', proposalId, payload)
}

async function recoverLocalApplyAckFromContext(context) {
  const proposalId = typeof context?.lastAppliedProposal === 'string'
    ? context.lastAppliedProposal
    : ''
  const documentId = typeof context?.documentId === 'string' ? context.documentId : ''
  const revision = Number(context?.revision)
  const resultHash = typeof context?.documentHash === 'string' ? context.documentHash : ''
  if (
    context?.mindmapId
    || !proposalId
    || !documentId
    || !Number.isSafeInteger(revision)
    || revision < 1
    || !resultHash
  ) return false
  const recoveryKey = `${proposalId}:${documentId}:${revision}:${resultHash}`
  if (localAckRecoveryCompleted.has(recoveryKey)) return true
  const result = await queueLocalApplyAck(proposalId, { documentId, revision, resultHash })
  if (result.sent > 0) {
    localAckRecoveryCompleted.add(recoveryKey)
    return true
  }
  if (result.receiptUnstored && !localAckRecoveryWarnings.has(recoveryKey)) {
    localAckRecoveryWarnings.add(recoveryKey)
    ElMessage.warning('检测到已应用但回执未保存；请恢复网络后重新打开 AI 面板重试')
  }
  return false
}

async function applyLocalProposal({
  proposalId,
  expectedSourceFingerprint,
  actionIdentity,
}) {
  const prepared = (await prepareMindmapAiLocalApply(proposalId)).data
  assertActionIdentity(actionIdentity)
  const { document, documentHash } = await assertMindmapAiArtifact(
    prepared.artifact,
    { requirePassed: true },
  )
  if (prepared.resultHash !== documentHash) {
    throw new Error('AI 提案结果与文件哈希不一致，已阻止应用')
  }
  assertActionIdentity(actionIdentity)
  await validateMindmapAiArtifact(prepared.artifact, true)
  assertActionIdentity(actionIdentity)
  const context = await requestEditorContext()
  assertActionIdentity(actionIdentity)
  if (context.readonly) throw new Error('发起编辑器当前为只读，不能应用 AI 提案')
  if (
    context.lastAppliedProposal === prepared.proposalId
    && context.documentHash === documentHash
  ) {
    const receipt = await queueLocalApplyAck(prepared.proposalId, {
      documentId: context.documentId,
      revision: context.revision,
      resultHash: documentHash,
    })
    assertActionIdentity(actionIdentity)
    return {
      receiptPending: receipt.pending > 0,
      receiptUnstored: receipt.receiptUnstored === true,
    }
  }
  if (
    context.documentId !== prepared.baseDocumentId
    || Number(context.revision) !== Number(prepared.baseRevision)
    || prepared.baseHash !== expectedSourceFingerprint
  ) throw new Error('当前本地脑图已发生变化，请基于最新内容重新生成')
  const verified = await verifyMindmapAiLocalProposal({
    baseDocument: context.document,
    operations: prepared.operations,
    baseHash: prepared.baseHash,
    resultHash: prepared.resultHash,
    artifactDocument: document,
    artifactHash: documentHash,
  })
  assertActionIdentity(actionIdentity)
  const applied = await emitEditorRequest('setData', verified.document, {
    aiLocalApply: {
      documentId: context.documentId,
      revision: context.revision,
      snapshotFingerprint: verified.baseHash,
      baseHash: verified.baseHash,
      proposalId: prepared.proposalId,
      resultHash: verified.resultHash,
    },
  })
  // setData 已经原子修改编辑器；即使弹窗随后关闭也必须先持久化 ACK，
  // 再依据身份栅栏决定是否更新当前弹窗状态。
  const receipt = await queueLocalApplyAck(prepared.proposalId, {
    documentId: applied.documentId,
    revision: applied.revision,
    resultHash: applied.resultHash,
  })
  assertActionIdentity(actionIdentity)
  return {
    receiptPending: receipt.pending > 0,
    receiptUnstored: receipt.receiptUnstored === true,
  }
}

async function applyCloudProposal({
  proposalId,
  sourceMindmapId,
  baseRevision,
  baseHash,
  baseRoomEpoch,
  actionIdentity,
  forceOverwrite = false,
}) {
  const context = await requestEditorContext()
  assertActionIdentity(actionIdentity)
  if (context.readonly) throw new Error('发起编辑器当前为只读，不能应用 AI 提案')
  if (Number(context.mindmapId) !== Number(sourceMindmapId)) {
    throw new Error('当前打开的脑图不是提案目标')
  }
  // 云端 revision 是否仍与 Proposal 等价只能由服务端权威文档裁决。
  // 浏览器运行时树包含渲染器瞬态字段，在这里重复计算会把内容等价的
  // 自动保存误判为冲突；服务端仍会执行哈希、room epoch 与写栅栏校验。
  const requestPayload = {
    contentRevision: baseRevision,
    baseHash,
    roomEpoch: baseRoomEpoch,
    forceOverwrite,
  }
  const idempotencyKey = forceOverwrite
    ? `mindmap-ai-force-apply:${proposalId}`
    : `mindmap-ai-apply:${proposalId}`
  // The durable intent must exist before the first irreversible request. If
  // localStorage is unavailable, fail closed and do not call the server.
  const intent = enqueueMindmapAiCloudMutationIntent({
    ownerUserId: currentAiOwnerUserId(),
    action: 'apply',
    jobId: actionIdentity.jobId,
    proposalId,
    mindmapId: context.mindmapId,
    idempotencyKey,
    requestPayload,
  })
  const result = await executeCloudMutationWithRecovery(intent)
  // Server reconciliation and editor reload deliberately ignore dialog
  // visibility. Only the following UI update is fenced by action identity.
  assertActionIdentity(actionIdentity)
  return result
}

async function refreshSourceContextAfterMutation(sourceMindmapId, actionIdentity) {
  const refreshedContext = await requestEditorContext().catch(() => null)
  assertActionIdentity(actionIdentity)
  if (!refreshedContext?.document?.root) return
  editorContext.value = refreshedContext
  const matchesSource = sourceMindmapId
    ? Number(refreshedContext.mindmapId) === Number(sourceMindmapId)
    : Boolean(
        sourceContext.value?.documentId
        && refreshedContext.documentId === sourceContext.value.documentId,
      )
  if (!matchesSource) return
  sourceContext.value = refreshedContext
  sourceFingerprint.value = await computeMindmapSnapshotFingerprint(refreshedContext.document)
  assertActionIdentity(actionIdentity)
  persistActiveJob()
}

async function applyProposal() {
  if (actionBusy.value) return false
  const currentJob = job.value
  const currentProposal = proposal.value
  if (!currentProposal || !diffConfirmed.value) {
    ElMessage.warning('请先查看并勾选提案差异确认，再应用到当前脑图')
    if (currentProposal) {
      await nextTick()
      const confirmationElement = proposalConfirmationRef.value?.$el
      confirmationElement?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      confirmationElement?.querySelector?.('input[type="checkbox"]')?.focus?.()
    }
    return false
  }
  const jobId = currentJob.id
  const proposalId = currentProposal.id
  const expectedSourceFingerprint = sourceFingerprint.value
  const sourceMindmapId = sourceContext.value?.mindmapId
  // 对云端提案，差异勾选就是用户对整图覆盖的明确授权。第一次请求直接进入
  // 服务端 forceOverwrite 路径，避免先报“协作版本已变化”再让用户重复确认。
  const directCloudOverwrite = Boolean(sourceMindmapId)
  applying.value = true
  const identity = beginActionIdentity('apply', { jobId, proposalId })
  try {
    const result = sourceMindmapId
      ? await applyCloudProposal({
          proposalId,
          sourceMindmapId,
          baseRevision: currentJob.baseRevision,
          baseHash: currentJob.baseHash,
          baseRoomEpoch: currentJob.baseRoomEpoch,
          actionIdentity: identity,
          forceOverwrite: directCloudOverwrite,
        })
      : await applyLocalProposal({
          proposalId,
          expectedSourceFingerprint,
          actionIdentity: identity,
        })
    assertActionIdentity(identity)
    if (sourceMindmapId) {
      await refreshAuthoritativeCloudMutationJob(identity, ['applied', 'undone'])
    } else {
      job.value = { ...job.value, status: 'applied', progress: 100 }
    }
    upsertSessionTurn(job.value)
    persistActiveJob()
    await refreshSourceContextAfterMutation(sourceMindmapId, identity)
    await refreshTimelineAfterSideEffect(identity)
    if (sourceMindmapId && job.value.status === 'undone') {
      ElMessage.warning('AI 提案曾成功应用，但已被后续撤销；当前画布已同步权威版本')
    } else if (result?.receiptUnstored) {
      ElMessage.warning('提案已应用但回执未保存；请恢复网络后重新打开 AI 面板重试')
    } else if (result?.receiptPending) {
      ElMessage.warning('提案已应用；回执因网络问题排队，联网后会自动补发')
    } else if (directCloudOverwrite) {
      ElMessage.success('AI 完整结果已覆盖当前脑图，可随时撤销')
    } else {
      ElMessage.success('AI 脑图提案已应用')
    }
    return true
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return false
    const reconciled = await reconcileJobAfterSideEffect(identity)
    if (reconciled?.status === 'applied') {
      if (sourceMindmapId) {
        ElMessage.warning('提案已由服务端应用；编辑器正在恢复权威版本，请稍后重试同步。')
      }
      return true
    }
    if (['AI_PROPOSAL_STALE', 'AI_APPLY_CONFLICT'].includes(resolveMindmapAiErrorCode(error))) {
      schedulePoll(0, true)
    }
    ElMessage.error(formatMindmapAiError(error, 'AI 脑图提案应用失败'))
    return false
  } finally {
    applying.value = false
  }
}

async function undoProposal() {
  if (actionBusy.value || !canUndoCurrentProposal.value) return
  const jobId = job.value.id
  const proposalId = job.value.proposalId
  const sourceMindmapId = sourceContext.value?.mindmapId
  undoing.value = true
  const identity = beginActionIdentity('undo', { jobId, proposalId })
  try {
    await ElMessageBox.confirm(
      sourceContext.value?.mindmapId
        ? '只有 AI 应用后没有其他协作者修改时才能撤销。'
        : '将通过单条组合历史恢复 AI 应用前的本地脑图。',
      '撤销本次 AI 应用',
      { type: 'warning', confirmButtonText: '确认撤销' },
    )
    assertActionIdentity(identity)
    const context = await requestEditorContext()
    assertActionIdentity(identity)
    if (context.readonly) throw new Error('发起编辑器当前为只读，不能撤销 AI 提案')
    if (sourceMindmapId) {
      if (Number(context.mindmapId) !== Number(sourceMindmapId)) {
        throw new Error('当前打开的脑图不是撤销目标')
      }
      const idempotencyKey = `mindmap-ai-undo:${proposalId}`
      const intent = enqueueMindmapAiCloudMutationIntent({
        ownerUserId: currentAiOwnerUserId(),
        action: 'undo',
        jobId,
        proposalId,
        mindmapId: sourceMindmapId,
        idempotencyKey,
        requestPayload: null,
      })
      await executeCloudMutationWithRecovery(intent)
      assertActionIdentity(identity)
      await refreshAuthoritativeCloudMutationJob(identity, ['undone'])
    } else {
      const reverted = await emitEditorRequest('undoLocalAiProposal', {
        proposalId,
        resultHash: proposal.value?.resultHash,
        revertedHash: proposal.value?.baseHash,
        serverApplied: job.value?.status === 'applied',
      })
      const receipt = await queueLocalUndoAck(proposalId, reverted)
      assertActionIdentity(identity)
      if (receipt.receiptUnstored) {
        ElMessage.warning('本地撤销已完成，但回执未保存；请保持当前页面并恢复网络后重试')
      } else if (receipt.pending > 0) {
        ElMessage.warning('本地撤销已完成；回执将在联网后自动补发')
      }
    }
    if (!sourceMindmapId) {
      job.value = { ...job.value, status: 'undone', progress: 100 }
    }
    upsertSessionTurn(job.value)
    persistActiveJob()
    await refreshSourceContextAfterMutation(sourceMindmapId, identity)
    await refreshTimelineAfterSideEffect(identity)
    ElMessage.success('本次 AI 应用已撤销')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    const reconciled = await reconcileJobAfterSideEffect(identity)
    if (reconciled?.status === 'undone') {
      ElMessage.warning('撤销请求已提交，已从服务端恢复撤销状态')
      return
    }
    ElMessage.error(formatMindmapAiError(error, 'AI 应用撤销失败'))
  } finally {
    undoing.value = false
  }
}

async function cancelJob() {
  const jobId = job.value?.id
  if (!jobId || actionBusy.value) return
  cancelling.value = true
  const identity = beginActionIdentity('cancel', { jobId })
  try {
    const response = await cancelMindmapAiJob(jobId)
    assertActionIdentity(identity)
    job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
    realtimeError.value = ''
    persistActiveJob()
    if (isTerminalStatus(job.value.status)) {
      stopRealtime('completed')
      stopPolling()
      if (job.value.artifactId) {
        await hydrateTerminalResources(jobId)
        assertActionIdentity(identity)
      }
      await refreshTimelineAfterSideEffect(identity)
      return
    }
    schedulePoll(200)
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    ElMessage.error(formatMindmapAiError(error, '取消任务失败'))
  } finally {
    cancelling.value = false
  }
}

async function deleteSessionRecord() {
  const sessionId = job.value?.sessionId
  if (!sessionId || actionBusy.value) return
  const jobId = job.value.id
  deletingSession.value = true
  const identity = beginActionIdentity('delete-session', { jobId })
  try {
    await ElMessageBox.confirm(
      running.value
        ? '删除整段会话记录会同时请求取消正在运行的任务，且无法恢复。'
        : '将删除本会话的所有轮次、提示词和审计记录，且无法恢复。',
      '删除 AI 会话记录',
      { type: 'warning', confirmButtonText: '确认删除', confirmButtonClass: 'el-button--danger' },
    )
    assertActionIdentity(identity)
    await deleteMindmapAiSession(sessionId)
    assertActionIdentity(identity)
    recentSessions.value = recentSessions.value.filter(item => item.sessionId !== sessionId)
    resetNewJob({ clearStoredJob: true, preserveForm: true })
    ElMessage.success('AI 会话记录已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    ElMessage.error(formatMindmapAiError(error, '删除 AI 会话记录失败'))
  } finally {
    deletingSession.value = false
  }
}

watch(() => form.sourceMode, (mode) => {
  if (mode === 'new' && form.intent !== 'create') {
    form.intent = 'create'
  }
  if (mode !== 'file') {
    uploadedFileArtifact.value = null
    uploadedFileName.value = ''
  }
  if (mode === 'current') form.layout = normalizedSourceLayout(editorContext.value?.document)
  if (mode === 'new') form.layout = 'logicalStructure'
  reconcileAgentSelection()
})

watch(() => form.scopeType, (scopeType) => {
  if (form.sourceMode === 'current' && scopeType !== 'document') {
    form.layout = normalizedSourceLayout(editorContext.value?.document)
  }
})

watch(discussionMode, () => {
  if (job.value && !canSwitchInteractionMode.value) return
  reconcileAgentSelection()
})

watch(() => props.readonly, async () => {
  if (!visible.value) return
  try {
    await requestEditorContext()
  } catch {}
})

watch(() => userStore.id, (nextUserId, previousUserId) => {
  if (String(nextUserId || '') === String(previousUserId || '')) return
  invalidateSessionList()
  recentSessions.value = []
  sessionListError.value = ''
  clearLocalAckRetryTimer()
  resetNewJob({ clearStoredJob: false, preserveForm: true })
  localAckRecoveryWarnings.clear()
  localAckRecoveryCompleted.clear()
  updateCloudMutationRecoveryNotice()
  if (currentAiOwnerUserId()) {
    void flushPendingCloudMutationIntents()
    void flushLocalApplyAcks()
  }
})

watch(() => agentEvents.value.length, async (_nextLength, previousLength) => {
  const currentTimeline = activityTimelineRef.value
  const shouldFollowLatest = !currentTimeline
    || previousLength === 0
    || currentTimeline.scrollHeight - currentTimeline.scrollTop - currentTimeline.clientHeight <= 48
  await nextTick()
  const timeline = activityTimelineRef.value
  if (timeline && shouldFollowLatest) timeline.scrollTop = timeline.scrollHeight
})

watch(() => running.value || submitting.value, (active) => {
  if (!active) {
    clearInterval(generationClockTimer)
    generationClockTimer = null
    return
  }
  generationClockNow.value = Date.now()
  if (generationClockTimer !== null) return
  generationClockTimer = window.setInterval(() => {
    generationClockNow.value = Date.now()
  }, 1_000)
}, { immediate: true })

async function onNetworkOnline() {
  await flushPendingCloudMutationIntents()
  await flushLocalApplyAcks()
  try { await requestEditorContext() } catch {}
  if (terminalHydrationState.value === 'error' && isTerminalStatus(job.value?.status)) {
    retryTerminalHydration()
  }
  if (running.value && job.value?.id) {
    schedulePoll(0)
    connectRealtime(job.value.id)
  }
}

function onNetworkOffline() {
  clearLocalAckRetryTimer()
  if (!running.value) return
  realtimeGeneration += 1
  clearTimeout(realtimeReconnectTimer)
  realtimeReconnectTimer = null
  realtimeController?.abort()
  realtimeController = null
  realtimeConnectionState.value = 'offline'
  stopPolling()
}

defineExpose({
  agentEvents,
  draftDocument,
  realtimeConnectionState,
  realtimeError,
  proposalError,
  resetNewJob,
})

onMounted(() => {
  bus.on('showAiMindmap', showDialog)
  bus.on('aiCloudMutationRecoveryReady', onCloudMutationRecoveryReady)
  bus.on('aiLocalJournalRecovered', onLocalAiJournalRecovered)
  bus.on('node_active', onEditorNodeActive)
  window.addEventListener('online', onNetworkOnline)
  window.addEventListener('offline', onNetworkOffline)
  void flushPendingCloudMutationIntents()
  void flushLocalApplyAcks()
})

onBeforeUnmount(() => {
  componentAlive = false
  clearInterval(generationClockTimer)
  generationClockTimer = null
  invalidateActionIdentity()
  clearTimeout(terminalHydrationRetryTimer)
  clearLocalAckRetryTimer()
  invalidateRestoreOperations({ clearError: false })
  invalidateSessionList()
  stopRealtime('idle')
  stopPolling()
  bus.off('showAiMindmap', showDialog)
  bus.off('aiCloudMutationRecoveryReady', onCloudMutationRecoveryReady)
  bus.off('aiLocalJournalRecovered', onLocalAiJournalRecovered)
  bus.off('node_active', onEditorNodeActive)
  window.removeEventListener('online', onNetworkOnline)
  window.removeEventListener('offline', onNetworkOffline)
})
</script>

<style lang="scss">
.aiDialogBody {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: minmax(260px, 300px) minmax(0, 1fr);
  gap: 16px;
}

.activitySidebar,
.controlPane,
.previewPanel {
  min-width: 0;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.activitySidebar {
  display: flex;
  min-height: 0;
  padding: 14px;
  flex-direction: column;
  overflow: hidden;
  background: var(--el-fill-color-extra-light);
}

.activityHeader,
.activityHeaderActions,
.previewHeader,
.previewActions,
.agentOption,
.jobHeader,
.resultSummary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.activityHeader {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);

  > div:first-child {
    display: grid;
    gap: 3px;
  }

  small { color: var(--el-text-color-secondary); }
}

.activityHeaderActions {
  align-items: flex-end;
  flex-direction: column;
  gap: 2px;
}

.turnArtifacts {
  display: grid;
  max-height: 132px;
  margin-top: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  overflow: auto;
  gap: 6px;

  > strong { font-size: 12px; }

  button {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 9px;
    border: 1px solid var(--el-border-color-light);
    border-radius: 8px;
    color: var(--el-text-color-regular);
    background: var(--el-bg-color);
    cursor: pointer;
    gap: 8px;

    small { color: var(--el-text-color-secondary); }
    &.is-selected {
      border-color: var(--el-color-primary);
      color: var(--el-color-primary);
      background: var(--el-color-primary-light-9);
    }
    &:disabled { cursor: not-allowed; opacity: 0.65; }
  }
}

.connectionBadge {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  font-size: 12px;
  white-space: nowrap;
  gap: 5px;

  i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--el-text-color-placeholder);
  }

  &.is-connected,
  &.is-completed {
    color: var(--el-color-success);
    background: var(--el-color-success-light-9);

    i { background: var(--el-color-success); }
  }

  &.is-connecting,
  &.is-reconnecting {
    color: var(--el-color-warning-dark-2);
    background: var(--el-color-warning-light-9);

    i {
      background: var(--el-color-warning);
      animation: aiPulse 1s ease-in-out infinite;
    }
  }

  &.is-offline {
    color: var(--el-color-danger);
    background: var(--el-color-danger-light-9);

    i { background: var(--el-color-danger); }
  }
}

.activityTimeline {
  position: relative;
  min-height: 0;
  margin: 12px 0 0;
  padding: 0 2px 0 18px;
  flex: 1 1 auto;
  overflow: auto;
  list-style: none;

  &::before {
    position: absolute;
    top: 6px;
    bottom: 8px;
    left: 5px;
    width: 1px;
    background: var(--el-border-color);
    content: '';
  }
}

.activityEmpty,
.previewEmpty {
  display: flex;
  min-height: 160px;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  flex-direction: column;
  color: var(--el-text-color-secondary);
  text-align: center;
  gap: 7px;

  strong { color: var(--el-text-color-primary); }

  span {
    max-width: 260px;
    font-size: 12px;
    line-height: 1.55;
  }
}

.privacyNotice {
  margin: 10px 0 0;
  color: var(--el-text-color-placeholder);
  font-size: 11px;
  line-height: 1.5;
}

.workspaceMain {
  display: grid;
  min-height: 0;
  grid-template-columns: minmax(390px, 0.82fr) minmax(480px, 1.18fr);
  gap: 16px;
}

.controlPane {
  padding: 14px;
  overflow: auto;
}

.previewPanel {
  display: flex;
  min-height: 0;
  padding: 14px;
  flex-direction: column;
  overflow: hidden;
  background: var(--el-fill-color-extra-light);
}

.previewHeader {
  padding-bottom: 12px;

  > div:first-child {
    display: grid;
    gap: 3px;
  }

  small { color: var(--el-text-color-secondary); }
}

.previewActions {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.previewMetric {
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  font-size: 12px;
  white-space: nowrap;
}

.previewError { margin-bottom: 10px; }

.previewCanvas {
  min-height: 360px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  flex: 1 1 auto;
  overflow: hidden;
  background-color: var(--el-bg-color);
  background-image: radial-gradient(var(--el-border-color-lighter) 1px, transparent 1px);
  background-size: 18px 18px;
}

.previewEmptyIcon {
  display: grid;
  width: 54px;
  height: 54px;
  margin-bottom: 4px;
  place-items: center;
  border-radius: 16px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: 30px;
}

.previewEmpty.is-running .previewEmptyIcon {
  animation: aiPulse 1.6s ease-in-out infinite;
}

.previewWaitStatus {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 7px;
}

.previewWaitTime {
  padding: 3px 9px;
  border-radius: 999px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  font-size: 12px;
  font-weight: 600;
}

.formGrid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

.compactGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.fullWidth { width: 100%; }

.aiSourceFileInput { display: none; }

.sourceFileRow {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 10px;

  span {
    overflow: hidden;
    color: var(--el-text-color-regular);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.agentOption small,
.jobHeader small,
.fieldHint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.agentOption {
  min-width: 0;

  > span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  > small {
    flex: 0 1 auto;
    max-width: 58%;
    overflow: hidden;
    text-align: right;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &.is-unavailable { color: var(--el-text-color-placeholder); }
}

.agentSelectionIssue,
.composerAgentIssue {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  border: 1px solid color-mix(in srgb, var(--el-color-warning) 30%, transparent);
  border-radius: 9px;
  color: var(--el-text-color-regular);
  background: var(--el-color-warning-light-9);
  font-size: 11px;
  line-height: 1.45;
  gap: 6px;

  .el-icon {
    flex: 0 0 auto;
    margin-top: 2px;
    color: var(--el-color-warning);
  }

  span {
    min-width: 0;
    overflow-wrap: anywhere;
  }
}

.agentSelectionIssue {
  margin-top: 7px;
  padding: 7px 8px;
}

.agentReadiness {
  display: flex;
  min-width: 0;
  margin-top: 7px;
  padding: 8px 9px;
  align-items: flex-start;
  border-radius: 9px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  gap: 8px;

  > i {
    width: 8px;
    height: 8px;
    margin-top: 5px;
    flex: 0 0 auto;
    border-radius: 50%;
    background: var(--el-text-color-placeholder);
  }

  > div { display: grid; min-width: 0; gap: 1px; }
  strong { font-size: 11px; line-height: 1.4; }
  small { color: var(--el-text-color-secondary); font-size: 10px; line-height: 1.45; }

  &.is-ready {
    background: var(--el-color-success-light-9);
    > i { background: var(--el-color-success); }
    strong { color: var(--el-color-success-dark-2); }
  }

  &.is-pending {
    background: var(--el-color-warning-light-9);
    > i { background: var(--el-color-warning); }
    strong { color: var(--el-color-warning-dark-2); }
  }

  &.is-unavailable {
    background: var(--el-color-danger-light-9);
    > i { background: var(--el-color-danger); }
    strong { color: var(--el-color-danger); }
  }
}

.agentDisclosureDetails {
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 11px;

  summary {
    width: fit-content;
    color: var(--el-text-color-secondary);
    cursor: pointer;
  }
}

.agentDisclosure {
  display: flex;
  margin-top: 7px;
  flex-wrap: wrap;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.45;
  gap: 4px 10px;

  span {
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
  }
}

.submissionStatus {
  display: flex;
  margin: 5px 0 7px;
  padding: 8px 9px;
  align-items: flex-start;
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 24%, transparent);
  border-radius: 9px;
  color: var(--el-text-color-regular);
  background: var(--el-color-primary-light-9);
  gap: 8px;

  > i {
    width: 8px;
    height: 8px;
    margin-top: 5px;
    flex: 0 0 auto;
    border-radius: 50%;
    background: var(--el-color-primary);
    animation: aiPulse 1s ease-in-out infinite;
  }

  > div { display: grid; min-width: 0; gap: 1px; }
  strong { font-size: 11px; line-height: 1.4; }
  small { color: var(--el-text-color-secondary); font-size: 10px; line-height: 1.45; }
}

.jobPanel {
  display: grid;
  margin-top: 4px;
  padding: 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  gap: 10px;
}

.jobHeader > div {
  display: grid;
  gap: 3px;
}

.resultSummary {
  color: var(--el-color-success);
  font-size: 13px;
}

.timelineLoadFailure,
.restoreFailure,
.proposalLoadFailure {
  display: grid;
  justify-items: start;
  gap: 8px;
}

.restoreFailure { margin-bottom: 12px; }

.restoreFailureActions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.needsInputPanel {
  display: grid;
  padding: 12px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
  gap: 8px;

  ol {
    margin: 0;
    padding-left: 22px;
  }
}

.proposalPreview,
.followupPanel,
.retryPanel {
  display: grid;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-light);
  gap: 10px;
}

.proposalPreview { margin: 0; }

.proposalReviewBody {
  display: grid;
  gap: 10px;
}

.proposalReviewSummary {
  display: flex;
  min-height: 38px;
  padding: 2px 0;
  align-items: center;
  justify-content: space-between;
  color: var(--el-text-color-primary);
  cursor: pointer;
  list-style: none;
  gap: 12px;

  &::-webkit-details-marker { display: none; }

  > span { display: grid; min-width: 0; gap: 2px; }
  strong { font-size: 12px; }
  small { color: var(--el-text-color-secondary); font-size: 11px; }
  .el-icon { flex: 0 0 auto; transition: transform 0.18s ease; }
}

.proposalPreview[open] .proposalReviewSummary {
  margin-bottom: 10px;

  .el-icon { transform: rotate(180deg); }
}

.followupPanel,
.retryPanel { padding-top: 12px; }

.followupActions,
.retryActions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.diffCounts {
  display: flex;
  flex-wrap: wrap;
  font-size: 13px;
  font-weight: 600;
  gap: 8px 16px;
}

.diffList {
  max-height: 160px;
  margin: 0;
  padding-left: 20px;
  overflow: auto;
  font-size: 13px;
}

@keyframes aiPulse {
  50% { opacity: 0.35; }
}

@media (max-width: 1240px) {
  .aiDialogBody { grid-template-columns: minmax(240px, 280px) minmax(0, 1fr); }

  .workspaceMain {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .controlPane { overflow: visible; }

  .previewPanel { min-height: 460px; }
}

@media (prefers-reduced-motion: reduce) {
  .connectionBadge i,
  .previewEmptyIcon { animation: none !important; }
}

@media (max-width: 760px) {
  .aiDialogBody {
    height: auto;
    grid-template-columns: 1fr;
  }

  .activitySidebar { max-height: 250px; }

  .workspaceMain { overflow: visible; }

  .formGrid,
  .compactGrid { grid-template-columns: 1fr; }

  .previewPanel { min-height: 400px; }

  .previewCanvas { min-height: 310px; }

  .previewHeader,
  .followupActions,
  .retryActions {
    align-items: stretch;
    flex-direction: column;
  }

  .previewActions { justify-content: flex-start; }
}
</style>

<style lang="scss">
/* XMind 风格的 AI 工作台：左侧对话、右侧唯一的实时脑图舞台。 */
.mindmapAiDrawer {
  --el-color-primary: #7a5af8;
  --el-color-primary-light-9: #f2efff;
  --ai-panel-bg: #f4f5f7;
  --ai-card-bg: #ffffff;
  --ai-ink: #20211f;
  --ai-muted: #72746f;
  --ai-border: rgba(25, 28, 24, 0.1);
  height: 100% !important;
  background: var(--ai-panel-bg);
  box-shadow: 10px 0 34px rgba(20, 24, 20, 0.12);

  .el-drawer__body {
    display: flex;
    min-height: 0;
    padding: 0;
    flex-direction: column;
    overflow: hidden;
  }

  .el-drawer__footer {
    padding: 10px 14px 14px;
    border-top: 1px solid var(--ai-border);
    background: color-mix(in srgb, var(--ai-panel-bg) 94%, transparent);
    backdrop-filter: blur(16px);
  }
}

.aiPanelHeader {
  display: flex;
  height: 58px;
  padding: 0 12px 0 16px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--ai-border);
  background: var(--ai-panel-bg);
}

.newConversationButton {
  display: inline-flex;
  min-width: 0;
  padding: 8px 10px;
  align-items: center;
  border: 0;
  border-radius: 9px;
  color: var(--ai-ink);
  background: transparent;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
  gap: 8px;

  > span:first-child {
    max-width: 210px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &:hover:not(:disabled) { background: rgba(25, 28, 24, 0.06); }
  &:disabled { cursor: not-allowed; opacity: 0.48; }
}

.headerChevron {
  color: var(--ai-muted);
  font-size: 12px;
  transform: translateY(-1px);
}

.aiPanelHeaderActions {
  display: flex;
  align-items: center;
  gap: 2px;

  .el-button.is-active {
    color: var(--el-color-primary);
    background: var(--el-color-primary-light-9);
  }
}

.mobilePreviewToggle,
.mobilePreviewBack {
  display: none;
}

.mindmapAiDrawer .aiDialogBody {
  display: flex;
  height: auto;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
  overflow-x: hidden;
  overflow-y: auto;
  gap: 0;
}

.mindmapAiDrawer .activitySidebar,
.mindmapAiDrawer .controlPane {
  min-width: 0;
  padding: 14px 18px;
  border: 0;
  border-radius: 0;
  background: transparent;
  overflow: visible;
}

.mindmapAiDrawer .activitySidebar {
  display: block;
  flex: 0 0 auto;
}

.mindmapAiDrawer .activityHeader {
  padding-bottom: 10px;
  border-color: var(--ai-border);

  > div:first-child {
    strong { color: var(--ai-ink); font-size: 13px; }
    small { color: var(--ai-muted); font-size: 11px; }
  }
}

.mindmapAiDrawer .activityHeaderActions {
  align-items: center;
  flex-direction: row;
}

.mindmapAiDrawer .activityTimeline {
  min-height: auto;
  margin-top: 12px;
  padding-left: 20px;
  overflow: visible;
}

.mindmapAiDrawer .conversationTimeline {
  display: grid;
  padding-left: 0;
  gap: 14px;

  &::before { display: none; }
}

.conversationTurn {
  display: grid;
  gap: 8px;
}

.conversationMessage {
  display: grid;
  padding: 10px 12px;
  border: 1px solid var(--ai-border);
  border-radius: 13px;
  background: var(--ai-card-bg);
  gap: 7px;

  &.is-user {
    margin-left: 34px;
    border-color: color-mix(in srgb, var(--el-color-primary) 23%, transparent);
    background: var(--el-color-primary-light-9);
  }

  &.is-assistant { margin-right: 18px; }

  > p {
    margin: 0;
    color: var(--ai-ink);
    font-size: 13px;
    line-height: 1.55;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }
}

.conversationMessageMeta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  color: var(--ai-muted);
  font-size: 11px;
  gap: 8px;

  strong { color: var(--ai-ink); font-size: 12px; }
}

.usageSummary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;

  span {
    padding: 3px 7px;
    border-radius: 999px;
    color: var(--ai-muted);
    background: #f0f1ed;
    font-size: 10px;
  }
}

.turnAudit {
  border-top: 1px solid var(--ai-border);
  color: var(--ai-muted);
  font-size: 11px;

  summary {
    padding-top: 7px;
    cursor: pointer;
    user-select: none;
  }

  > ol {
    display: grid;
    margin: 7px 0 0;
    padding: 0;
    list-style: none;
    gap: 5px;

    li {
      position: relative;
      display: grid;
      padding: 7px 8px 7px 18px;
      border-radius: 8px;
      background: #f6f7f4;
      gap: 2px;

      &::before {
        position: absolute;
        top: 11px;
        left: 8px;
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: var(--el-color-primary);
        content: '';
      }

      span { color: var(--ai-ink); font-weight: 600; }
      p { margin: 0; line-height: 1.45; overflow-wrap: anywhere; }
      time { color: var(--el-text-color-placeholder); font-size: 10px; }
    }
  }

  > small { display: block; margin-top: 6px; }
}

.mindmapAiDrawer .turnArtifacts {
  display: flex;
  max-height: none;
  padding: 0 0 10px;
  overflow-x: auto;
  border-color: var(--ai-border);

  > strong { display: none; }
  button { min-width: max-content; padding: 6px 9px; }
}

.mindmapAiDrawer .privacyNotice {
  margin-bottom: 0;
  color: var(--ai-muted);
}

.mindmapAiDrawer .workspaceMain {
  display: block;
  min-height: auto;
}

.aiWelcome {
  display: flex;
  min-height: 410px;
  padding: 52px 4px 24px;
  align-items: center;
  flex-direction: column;
  text-align: center;

  .aiWelcomeMark {
    display: grid;
    width: 46px;
    height: 46px;
    margin-bottom: 18px;
    place-items: center;
    border: 1px solid rgba(122, 90, 248, 0.12);
    border-radius: 50%;
    color: #7657f6;
    background: linear-gradient(145deg, #ffffff, #eee9ff);
    box-shadow: 0 8px 24px rgba(98, 71, 208, 0.15);
    font-size: 22px;
  }

  h2 { margin: 0; color: var(--ai-ink); font-size: 22px; letter-spacing: -0.02em; }
}

.starterGrid {
  display: grid;
  width: 100%;
  margin-top: 30px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;

  button {
    display: flex;
    min-height: 88px;
    padding: 14px;
    align-items: flex-start;
    border: 1px solid var(--ai-border);
    border-radius: 13px;
    color: var(--ai-ink);
    background: var(--ai-card-bg);
    text-align: left;
    cursor: pointer;
    transition: transform 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
    gap: 9px;

    .el-icon { margin-top: 2px; color: var(--el-color-primary); font-size: 17px; }
    span { font-size: 13px; line-height: 1.45; }

    &:hover {
      border-color: color-mix(in srgb, var(--el-color-primary) 36%, transparent);
      box-shadow: 0 6px 18px rgba(20, 24, 20, 0.07);
      transform: translateY(-1px);
    }
  }
}

.advancedSettings {
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid var(--ai-border);
  border-radius: 14px;
  background: var(--ai-card-bg);
}

.advancedSettingsHeader {
  display: flex;
  margin-bottom: 14px;
  align-items: flex-start;
  justify-content: space-between;

  > div { display: grid; gap: 3px; }
  strong { color: var(--ai-ink); font-size: 14px; }
  small { color: var(--ai-muted); font-size: 11px; line-height: 1.4; }
}

.mindmapAiDrawer .formGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.mindmapAiDrawer .agentDisclosure { margin-top: 6px; }

.mindmapAiDrawer .jobPanel {
  margin: 0;
  padding: 14px;
  border-color: var(--ai-border);
  border-radius: 14px;
  background: var(--ai-card-bg);
  box-shadow: 0 1px 3px rgba(20, 24, 20, 0.04);
}

.mindmapAiDrawer .jobHeader small {
  display: block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mindmapAiDrawer .followupPanel,
.mindmapAiDrawer .retryPanel { display: none; }

.mindmapAiDrawer .proposalPreview {
  padding-top: 12px;
  border-color: var(--ai-border);
}

.mindmapAiDrawer .proposalReviewSummary {
  margin: -4px 0;
  padding: 4px 1px;
  border-radius: 8px;

  &:focus-visible {
    outline: 2px solid var(--el-color-primary-light-5);
    outline-offset: 2px;
  }
}

.mindmapAiDrawer .diffCounts {
  span {
    padding: 4px 8px;
    border-radius: 999px;
    background: var(--el-fill-color-light);
    font-size: 12px;
  }
}

.mindmapAiDrawer .diffList { max-height: 138px; padding-left: 18px; font-size: 12px; }

.panelFooter { display: grid; gap: 9px; }

.resultQuickActions {
  display: flex;
  min-height: 30px;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;

  .el-button {
    min-height: 30px;
    margin-left: 0;
    border-radius: 9px;
  }
}

.primaryResultAction {
  display: flex;
  padding: 10px 11px;
  align-items: center;
  justify-content: space-between;
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 22%, transparent);
  border-radius: 12px;
  background: var(--el-color-primary-light-9);
  gap: 12px;

  > div { display: grid; gap: 2px; text-align: left; }
  strong { color: var(--el-text-color-primary); font-size: 12px; }
  span { color: var(--el-text-color-secondary); font-size: 11px; }
}

.aiComposer {
  padding: 10px;
  border: 1px solid rgba(25, 28, 24, 0.16);
  border-radius: 15px;
  background: var(--ai-card-bg);
  box-shadow: 0 8px 26px rgba(20, 24, 20, 0.09);

  &.is-discussion { border-color: color-mix(in srgb, var(--el-color-primary) 34%, transparent); }

  .el-textarea__inner {
    padding: 6px 4px 8px;
    border: 0;
    box-shadow: none;
    background: transparent;
    font-size: 14px;
    line-height: 1.55;
  }
}

.composerAgentIssue {
  margin: 5px 0 4px;
  padding: 6px 8px;
  align-items: center;

  span { flex: 1 1 auto; }

  button {
    flex: 0 0 auto;
    padding: 2px 0;
    border: 0;
    color: var(--el-color-primary);
    background: transparent;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
}

.composerContextRow,
.composerToolbar,
.composerTools,
.composerSubmitGroup {
  display: flex;
  align-items: center;
}

.composerContextRow { min-height: 26px; flex-wrap: wrap; gap: 6px; }
.composerToolbar { justify-content: space-between; gap: 8px; }
.composerTools,
.composerSubmitGroup { gap: 4px; }

.contextChip,
.discussionChip {
  display: inline-flex;
  max-width: 270px;
  padding: 4px 8px;
  align-items: center;
  border-radius: 999px;
  color: var(--ai-muted);
  background: #f0f1ed;
  font-size: 11px;
  line-height: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  gap: 5px;
}

button.contextChip {
  border: 0;
  font-family: inherit;
  cursor: pointer;

  &:hover:not(:disabled) { color: var(--ai-ink); background: #e8e9e4; }
  &:disabled { cursor: default; opacity: 0.72; }
}

.discussionChip {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.reasoningModes {
  display: flex;
  padding: 2px;
  border-radius: 9px;
  background: #f0f1ed;

  button {
    padding: 5px 7px;
    border: 0;
    border-radius: 7px;
    color: var(--ai-muted);
    background: transparent;
    font-size: 11px;
    cursor: pointer;

    &.is-active { color: var(--ai-ink); background: #fff; box-shadow: 0 1px 3px rgba(20, 24, 20, 0.12); }
    &:disabled { cursor: default; opacity: 0.7; }
  }
}

.aiDraftStage {
  position: fixed;
  z-index: 1900;
  top: 58px;
  right: 0;
  bottom: 0;
  left: 500px;
  display: flex;
  min-height: 0;
  padding: 18px;
  border: 0;
  border-left: 1px solid rgba(25, 28, 24, 0.08);
  border-radius: 0;
  background: #f7f8f5;
  box-shadow: none;

  .previewHeader {
    position: absolute;
    z-index: 2;
    top: 14px;
    right: 18px;
    left: 18px;
    padding: 9px 10px;
    border: 1px solid rgba(25, 28, 24, 0.08);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.9);
    box-shadow: 0 4px 18px rgba(20, 24, 20, 0.06);
    backdrop-filter: blur(12px);
  }

  .previewCanvas {
    min-height: 0;
    margin-top: 56px;
    border: 0;
    border-radius: 14px;
    background-color: #fff;
  }
}

.mindmapAiSessionPopper,
.mindmapAiContextPopper,
.mindmapAiSelectPopper,
.mindmapAiTooltipPopper {
  z-index: 4300 !important;
}

.mindmapAiSessionPopper,
.mindmapAiContextPopper {
  padding: 8px !important;
  border-color: rgba(25, 28, 24, 0.1) !important;
  border-radius: 14px !important;
  box-shadow: 0 14px 42px rgba(20, 24, 20, 0.16) !important;
}

.sessionMenu,
.contextMenu {
  display: grid;
  gap: 4px;
}

.sessionNewAction,
.sessionList > button,
.contextMenu > button {
  display: flex;
  width: 100%;
  padding: 9px 10px;
  align-items: center;
  border: 0;
  border-radius: 9px;
  color: var(--el-text-color-primary);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  gap: 9px;

  &:hover:not(:disabled),
  &.is-current { background: var(--el-fill-color-light); }
  &:disabled { cursor: not-allowed; opacity: 0.48; }
}

.sessionNewAction > span:last-child,
.sessionListCopy,
.contextMenu > button {
  min-width: 0;
}

.sessionNewAction > span:last-child,
.sessionListCopy,
.contextMenu > button {
  strong,
  small { display: block; }
  strong { font-size: 12px; }
  small { margin-top: 2px; color: var(--el-text-color-secondary); font-size: 10px; }
}

.sessionMenuHeading {
  display: flex;
  margin-top: 3px;
  padding: 7px 8px 4px;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 10px;

  button { border: 0; color: var(--el-color-primary); background: transparent; cursor: pointer; }
}

.sessionList {
  display: grid;
  max-height: 310px;
  overflow: auto;
  gap: 2px;

  > button { justify-content: space-between; }
  time { color: var(--el-text-color-placeholder); font-size: 10px; white-space: nowrap; }
}

.sessionListCopy {
  flex: 1 1 auto;

  strong {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.sessionMenuState {
  padding: 14px 10px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  text-align: center;

  &.is-error { color: var(--el-color-warning-dark-2); }
}

.contextMenu > button {
  display: block;

  &[aria-checked='true'] {
    color: var(--el-color-primary);
    background: var(--el-color-primary-light-9);
  }
}

@media (prefers-reduced-motion: reduce) {
  .starterGrid button { transition: none; }
}

@media (max-width: 760px) {
  .mindmapAiDrawer { width: 100% !important; }
  .mobilePreviewToggle { display: inline-flex; }

  .aiDraftStage:not(.is-mobile-visible) { display: none; }

  .aiDraftStage.is-mobile-visible {
    z-index: 4100;
    top: 0;
    right: 0;
    bottom: 0;
    left: 0;
    display: flex;
    padding: 12px;

    .previewHeader {
      top: 12px;
      right: 12px;
      left: 12px;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
    }

    .previewCanvas { margin-top: 70px; }
  }

  .mobilePreviewBack { display: inline-flex; }
  .starterGrid,
  .mindmapAiDrawer .formGrid { grid-template-columns: 1fr; }
  .reasoningModes button { padding-inline: 6px; }
}
</style>
