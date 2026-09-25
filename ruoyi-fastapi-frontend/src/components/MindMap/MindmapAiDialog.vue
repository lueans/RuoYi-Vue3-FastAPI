<template>
  <el-drawer
    v-model="visible"
    class="mindmapAiDrawer"
    :class="{ isDark: settingsStore.isDark }"
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
        :disabled="running || actionBusy || livePreviewCanvasMutationBlocked"
        @show="loadRecentSessions"
      >
        <template #reference>
          <button
            type="button"
            class="newConversationButton"
            :disabled="running || actionBusy || livePreviewCanvasMutationBlocked"
            aria-haspopup="menu"
            :aria-expanded="sessionMenuVisible"
          >
            <span>{{ currentSessionTitle }}</span>
            <el-icon class="headerChevron" aria-hidden="true"><ArrowDown /></el-icon>
          </button>
        </template>
        <div class="sessionMenu" role="menu" aria-label="AI 对话历史">
          <button
            type="button"
            class="sessionNewAction"
            role="menuitem"
            :disabled="livePreviewCanvasMutationBlocked"
            @click="startNewJob"
          >
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
              :disabled="Boolean(sessionUnavailableReason(session)) || livePreviewCanvasMutationBlocked"
              :title="livePreviewCanvasMutationBlocked
                ? '请先采纳或不采纳当前 AI 实时预览'
                : sessionUnavailableReason(session) || session.title"
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
          <el-button circle text aria-label="关闭 AI 面板" @click="requestDialogClose">
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
            <small>{{ conversationTurns.length + (pendingFollowupPrompt ? 1 : 0) }} 轮对话 · 生成过程可展开</small>
          </div>
          <div class="activityHeaderActions">
            <el-button
              v-if="job?.sessionId"
              link
              type="danger"
              :loading="deletingSession"
              :disabled="actionBusy || livePreviewCanvasMutationBlocked"
              @click="deleteSessionRecord"
            >删除记录</el-button>
          </div>
        </div>
        <el-skeleton v-if="timelineLoading && !conversationTurns.length" :rows="5" animated />
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
            :disabled="!job?.sessionId || livePreviewCanvasMutationBlocked"
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
            :disabled="selectedArtifactLoading || actionBusy || livePreviewCanvasMutationBlocked"
            @click="selectSessionTurn(turn)"
          >
            <span>第 {{ turn.job.turnIndex || 1 }} 轮</span>
            <small>{{ jobStatusLabels[turn.job.status] || turn.job.status }}</small>
          </button>
          <button
            v-if="job && !job.artifactId"
            type="button"
            :class="{ 'is-selected': selectedTurnJobId === String(job.id) }"
            :disabled="selectedArtifactLoading || actionBusy || livePreviewCanvasMutationBlocked"
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
              <section v-if="turn.tagSuggestions.items.length" class="tagSuggestions" aria-label="本轮标签建议">
                <strong>标签建议 · 未创建、未绑定</strong>
                <p>本轮仅提出建议。请手动创建标签后，在下一轮要求 AI 引用；不会自动创建或继续执行。</p>
                <ul>
                  <li v-for="suggestion in turn.tagSuggestions.items" :key="suggestion.key">
                    <strong>{{ suggestion.name }}</strong>
                    <p v-if="suggestion.reason">{{ suggestion.reason }}</p>
                    <small v-if="suggestion.nodeUids.length">
                      建议关联 {{ suggestion.nodeUids.length }} 个节点{{ suggestion.nodeUidsTruncated ? '（数量已截断）' : '' }}
                    </small>
                  </li>
                </ul>
                <small v-if="turn.tagSuggestions.truncated">展示已达上限，部分建议、说明或目标节点已省略。</small>
              </section>
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
          <li v-if="pendingFollowupPrompt" class="conversationTurn">
            <div class="conversationMessage is-user">
              <div class="conversationMessageMeta"><strong>你</strong></div>
              <p>{{ pendingFollowupPrompt }}</p>
            </div>
            <div class="conversationMessage is-assistant">
              <div class="conversationMessageMeta"><strong>AI · 新一轮</strong><span>正在创建</span></div>
              <p>正在准备本轮任务…</p>
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
                :disabled="livePreviewCanvasMutationBlocked"
                @click="retryCloudMutationRecovery"
              >重新同步云端 AI 操作</el-button>
              <el-button
                v-if="cloudMutationHasPermanentFailure"
                size="small"
                type="danger"
                plain
                :disabled="cloudMutationRecovering || livePreviewCanvasMutationBlocked"
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
                :disabled="restoringJob || (livePreviewCanvasMutationBlocked && !directCanvasRecoveryJobId)"
                @click="retryStoredJobRecovery"
              >重试恢复任务</el-button>
              <el-button
                size="small"
                :disabled="restoringJob || livePreviewCanvasMutationBlocked"
                @click="discardStoredJobRecovery"
              >
                放弃恢复并新建
              </el-button>
            </div>
          </div>
          <div
            v-if="livePreviewPreparing"
            class="liveDraftNotice is-preparing"
            role="status"
            aria-live="off"
          >
            <i aria-hidden="true"></i>
            <div>
              <strong>{{ livePreviewPreparingTitle }}</strong>
              <span>{{ livePreviewPreparingDescription }}</span>
            </div>
          </div>
          <div
            v-if="livePreviewNoticeVisible"
            ref="livePreviewNoticeRef"
            class="liveDraftNotice"
            :class="{ 'is-complete': !running && !applying && !cancelling && !livePreviewReverting && !livePreviewPaused && !livePreviewCatchingUp }"
            role="status"
            aria-live="off"
            tabindex="-1"
          >
            <i aria-hidden="true"></i>
            <div>
              <strong>{{ livePreviewNoticeTitle }}</strong>
              <span>{{ livePreviewNoticeDescription }}</span>
            </div>
            <el-button
              v-if="livePreviewPlaybackAvailable"
              class="livePreviewPlaybackButton"
              size="small"
              text
              :disabled="livePreviewRendering"
              @click="toggleLivePreviewPlayback()"
            >{{ livePreviewPaused ? '继续显示' : '暂停显示' }}</el-button>
          </div>
          <div
            v-if="directExecutionNoticeVisible"
            class="liveDraftNotice is-direct"
            :class="{ 'is-complete': !running }"
            role="status"
            aria-live="polite"
          >
            <i aria-hidden="true"></i>
            <div>
              <strong>{{ directExecutionNoticeTitle }}</strong>
              <span>{{ directExecutionNoticeDescription }}</span>
            </div>
          </div>
          <p
            v-if="livePreviewAccessibleAnnouncement"
            class="mindmapAiSrOnly"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >{{ livePreviewAccessibleAnnouncement }}</p>
          <el-alert
            v-if="livePreviewError"
            :title="livePreviewError"
            type="warning"
            show-icon
            :closable="false"
          />
          <el-button
            v-if="uncertainCanvasCreation"
            size="small"
            type="warning"
            plain
            :loading="livePreviewRecovering"
            @click="reconcilePendingCanvasCreation"
          >确认创建结果并恢复</el-button>
          <el-button
            v-if="livePreviewError && directCanvasOwned && !uncertainCanvasCreation"
            size="small"
            type="warning"
            plain
            :loading="livePreviewRecovering"
            @click="retryLivePreviewSync"
          >{{ isTerminalStatus(job?.status) ? '重新同步云端结果' : '重试流式显示' }}</el-button>
          <el-button
            v-if="job?.status === 'ready' && livePreviewAutoAcceptFailedJobId === String(job.id)"
            size="small"
            type="warning"
            plain
            :loading="applying"
            :disabled="actionBusy"
            @click="acceptCompletedLivePreviewByDefault(job.id, { retry: true })"
          >重试保存 AI 结果</el-button>
          <el-alert
            v-if="realtimeError"
            :title="realtimeError"
            type="warning"
            show-icon
            :closable="false"
          />
          <div v-if="livePreviewRecoveryAvailable" class="livePreviewRecovery" role="status">
            <span>已保留当前画布内容，可以立即尝试恢复实时草稿同步。</span>
            <el-button
              size="small"
              type="warning"
              plain
              :loading="livePreviewRecovering"
              :disabled="actionBusy || livePreviewRecovering"
              @click="retryLivePreviewSync"
            >重新同步画布</el-button>
          </div>
          <div v-if="draftFreshnessMessage" class="draftFreshnessRecovery">
            <el-alert
              :title="draftFreshnessMessage"
              :type="['stale', 'restarted'].includes(draftFreshness) ? 'warning' : 'info'"
              show-icon
              :closable="false"
            />
            <el-button
              v-if="sourceBaselineMismatch"
              size="small"
              type="warning"
              plain
              :disabled="actionBusy || livePreviewCanvasMutationBlocked"
              @click="startNewJob"
            >基于当前脑图重新生成</el-button>
          </div>
          <el-alert
            v-if="viewingHistoricalArtifact"
            :title="`正在查看第 ${selectedArtifactJob?.turnIndex || 1} 轮历史结果；应用与撤销仍锁定当前轮次。`"
            type="info"
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

          <section v-if="!job && !agentEvents.length" class="aiWelcome">
            <div class="aiWelcomeMark" aria-hidden="true">
              <el-icon><MagicStick /></el-icon>
            </div>
            <h2>今天想做点什么？</h2>
            <div class="starterGrid">
              <button
                v-for="starter in starterItems"
                :key="starter.type"
                type="button"
                @click="usePromptStarter(starter.type)"
              >
                <el-icon><MagicStick /></el-icon>
                <span>{{ starter.label }}</span>
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
                :label="`${model.modelName || model.modelCode} · ${model.provider}/${model.modelCode}`"
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

        <div class="formGrid">
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
            <div v-if="targetLayoutLocked" class="fieldHint">局部编辑只修改授权节点，保持当前脑图布局。</div>
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
          <el-form-item v-if="!discussionMode" label="生成方式">
            <el-select
              v-model="form.generationMode"
              class="fullWidth"
              popper-class="mindmapAiSelectPopper"
              :disabled="taskConfigurationLocked"
            >
              <el-option
                v-for="item in generationModeOptions"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
            <div class="fieldHint">{{ generationModeHint }}</div>
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
          <span class="jobActivitySummary">{{ jobActivitySummary }}</span>
        </div>
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
            @click="loadProposal"
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
          ref="proposalReviewRef"
          class="proposalPreview"
          :open="!proposalReviewFinalized"
          aria-label="AI 提案差异预览"
          tabindex="-1"
        >
          <summary v-if="proposalReviewFinalized" class="proposalReviewSummary">
            <span>
              <strong>{{ job.status === 'undone'
                ? '已撤销提案差异'
                : job.status === 'rejected' ? '已拒绝提案差异' : '已应用提案差异' }}</strong>
              <small v-if="resultImpactSummaryAvailable">
                新增 {{ resultImpactForDisplay.createdCount }} ·
                修改 {{ resultImpactForDisplay.updatedCount }} ·
                移动 {{ resultImpactForDisplay.movedCount }} ·
                删除 {{ resultImpactForDisplay.deletedCount }}
              </small>
              <small v-else>变更统计暂不可用，已完成的云端直写仍可在脑图正文中查看</small>
            </span>
            <el-icon aria-hidden="true"><ArrowDown /></el-icon>
          </summary>
          <div class="proposalReviewBody">
            <div v-if="resultImpactSummaryAvailable" class="diffCounts">
              <span>新增 {{ resultImpactForDisplay.createdCount }}</span>
              <span>修改 {{ resultImpactForDisplay.updatedCount }}</span>
              <span>移动 {{ resultImpactForDisplay.movedCount }}</span>
              <span>删除 {{ resultImpactForDisplay.deletedCount }}</span>
            </div>
            <div v-else class="diffCounts is-unavailable">变更统计暂不可用</div>
            <el-alert
              v-if="resultImpactForDisplay?.highImpact"
              :title="resultImpactForDisplay.highImpactReasons?.join('；') || '这是高影响提案'"
              type="warning"
              show-icon
              :closable="false"
            />
            <ul v-if="resultImpactForDisplay?.changes?.length" class="diffList">
              <li
                v-for="(change, index) in resultImpactForDisplay.changes.slice(0, 12)"
                :key="`${change.type}:${change.nodeUid || index}`"
              >
                {{ changeTypeLabel(change.type) }} · {{ change.path || change.fromPath || '文档设置' }}
                <span v-if="change.subtreeSize">（子树 {{ change.subtreeSize }} 个节点）</span>
              </li>
            </ul>
            <div v-if="resultImpactForDisplay?.changes?.length > 12" class="fieldHint">
              另有 {{ resultImpactForDisplay.changes.length - 12 }} 项变化未展开。
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
          </section>
        </section>

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
            :disabled="actionBusy || livePreviewCanvasMutationBlocked"
            :title="livePreviewCanvasMutationBlocked ? '请先采纳或不采纳当前 AI 实时预览' : undefined"
            @click="openArtifactAsLocal"
          >打开为本地脑图</el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && job.status === 'ready' && canReplaceLocal"
            size="small"
            plain
            :loading="replacingLocal"
            :disabled="actionBusy || livePreviewCanvasMutationBlocked"
            :title="livePreviewCanvasMutationBlocked ? '请先采纳或不采纳当前 AI 实时预览' : undefined"
            @click="replaceLocalWithArtifact"
          >替换当前本地脑图</el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && job.status === 'ready' && canInsertLocal"
            size="small"
            plain
            :loading="insertingLocal"
            :title="livePreviewCanvasMutationBlocked ? '请先采纳或不采纳当前 AI 实时预览' : undefined"
            :disabled="actionBusy || livePreviewCanvasMutationBlocked"
            @click="insertArtifactBranch"
          >插入分支</el-button>
          <el-button
            v-if="!viewingHistoricalArtifact && job?.artifactId && job.status === 'ready'"
            size="small"
            type="primary"
            :loading="savingCloud"
            :disabled="actionBusy || livePreviewCanvasMutationBlocked"
            :title="livePreviewCanvasMutationBlocked ? '请先采纳或不采纳当前 AI 实时预览' : undefined"
            @click="saveCloud"
          >保存为云端脑图</el-button>
        </div>

        <div v-if="canRejectLiveDraft" class="primaryResultAction liveDraftAction">
          <div>
            <strong>{{ job?.status === 'ready' ? 'AI 结果已完成 · 已保留在当前脑图' : 'AI 正在实时编辑' }}</strong>
            <span>{{ job?.status === 'ready'
              ? '当前结果已经保存；撤销可恢复生成前版本。'
              : '停止任务会保留已生成修改；如果不需要，可撤销本轮。' }}</span>
          </div>
          <el-button
            type="warning"
            plain
            :loading="cancelling"
            :disabled="actionBusy"
            @click="rejectLiveDraft"
          >{{ job?.status === 'ready' ? '撤销本轮 AI 修改' : '不采纳并撤销' }}</el-button>
        </div>

        <div
          v-if="highImpactReviewRequired"
          class="primaryResultAction liveDraftAction is-review-required"
        >
          <div>
            <strong>AI 结果需要你确认</strong>
            <span>{{ livePreviewActive
              ? '结果已经实时展示在当前画布；请查看差异后明确采纳，或不采纳本轮修改。'
              : '本轮结果等待你的决定；可以查看差异并采纳，也可以不采纳本轮修改。' }}</span>
          </div>
          <el-button
            type="warning"
            plain
            :loading="rejectingReview"
            :disabled="actionBusy"
            @click="rejectLiveDraft"
          >不采纳本轮</el-button>
          <el-button
            type="primary"
            :loading="applying"
            :disabled="actionBusy"
            @click="applyProposal()"
          >查看差异并采纳</el-button>
        </div>

        <div
          v-if="job?.status === 'rejected' && !viewingHistoricalArtifact"
          class="primaryResultAction liveDraftAction is-rejected"
        >
          <div>
            <strong>本轮变更未采纳 · 当前脑图保持原内容</strong>
            <span>可以修改要求，基于当前脑图重新开始一轮；这会创建新的确认边界。</span>
          </div>
          <el-button
            type="primary"
            plain
            :disabled="actionBusy"
            @click="startRevisionFromRejected"
          >修改要求重新生成</el-button>
        </div>

        <div v-if="(canApplyCurrentProposal && !livePreviewActive) || canUndoCurrentProposal" class="primaryResultAction">
          <div v-if="canApplyCurrentProposal && !livePreviewActive">
            <strong>{{ livePreviewAutoAcceptFailedJobId === String(job?.id) ? 'AI 结果保存未完成' : 'AI 结果已完成，正在保存' }}</strong>
            <span>保存完成后可撤销本次 AI 全部操作</span>
          </div>
          <div v-else>
            <strong>AI 结果已保存</strong>
            <span>当前画布保持生成结果，如需恢复可撤销本次 AI 全部操作</span>
          </div>
          <el-button
            v-if="canUndoCurrentProposal"
            type="warning"
            plain
            :loading="undoing"
            :disabled="actionBusy && !undoing"
            @click="undoProposal"
          >撤销 AI 结果</el-button>
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
            ref="composerInputRef"
            v-model="composerText"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            maxlength="20000"
            resize="none"
            :disabled="!composerEnabled"
            :placeholder="composerPlaceholder"
            @keydown="onComposerKeydown"
          />
          <div v-if="composerPreflightText" class="composerPreflight" role="status">
            <span class="composerPreflightLabel">发送前确认</span>
            <span>{{ composerPreflightText }}</span>
          </div>
          <div v-if="running" class="composerRoutePicker" role="group" aria-label="运行中消息去向">
            <span class="composerRouteLabel">这条要求：</span>
            <button
              type="button"
              :class="{ 'is-active': runningMessageRoute === 'current' }"
              :disabled="composerSending || actionBusy"
              title="不打断当前已提交修改，在下一个安全边界采用"
              @click="runningMessageRoute = 'current'"
            >加入当前任务</button>
            <button
              type="button"
              :class="{ 'is-active': runningMessageRoute === 'next' }"
              :disabled="composerSending || actionBusy"
              title="当前轮结束后按队列顺序开始"
              @click="runningMessageRoute = 'next'"
            >排到下一轮</button>
            <span class="composerRouteHint">
              {{ runningMessageRoute === 'current'
                ? '将在下一个安全边界采用，不会打断当前画布更新。'
                : '当前轮完成后自动开始，并显示队列位置。' }}
            </span>
          </div>
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
                type="primary"
                aria-label="排到下一轮"
                :loading="composerSending"
                :disabled="!composerCanSend"
                @click="sendComposerMessage"
              ><el-icon v-if="!composerSending"><Promotion /></el-icon></el-button>
              <el-button
                v-if="running"
                circle
                aria-label="停止任务并保留已生成结果"
                title="停止任务并保留已生成结果"
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
import { useRoute } from 'vue-router'
import {
  ArrowDown,
  ArrowUp,
  Close,
  MagicStick,
  MoreFilled,
  Paperclip,
  Plus,
  Promotion,
  Setting,
  WarningFilled,
} from '@element-plus/icons-vue'
import { listModelAll } from '@/api/ai/model'
import useSettingsStore from '@/store/modules/settings'
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
  rejectMindmapAiProposal,
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
  compareMindmapAiPreviewCoordinates,
  countMindmapAiDraftNodes,
  describeMindmapAiDraftChange,
  nextMindmapAiDraftFrame,
  summarizeMindmapAiDraftChanges,
} from '@/utils/mindmap-ai-live-preview'
import {
  getMindmapAiPendingCharacterCount,
  getMindmapAiPlaybackPacing,
} from '@/utils/mindmap-ai-playback-pacing'
import {
  directImpactForMindmapAiResult,
  resolveMindmapAiDirectChangeSummary,
} from '@/utils/mindmap-ai-result-summary'
import {
  collectMindmapAiTagSuggestions,
  sanitizeMindmapAiTagSuggestionsPayload,
} from '@/utils/mindmap-ai-tag-suggestions'
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
  isMindmapAiAbortError as isAbortError,
  resolveMindmapAiErrorCode,
} from '@/utils/mindmap-ai-errors'
import { normalizeNumericOwnerUserId, sha256Hex } from '@/utils/mindmap-ai-shared'
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
import bus from './useEventBus'

const props = defineProps({
  readonly: { type: Boolean, default: false },
})
const route = useRoute()
const router = useRouter()
const settingsStore = useSettingsStore()
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
const preparingCanvas = ref(false)
// Canvas ownership belongs to a specific task, never to the currently selected
// conversation. Stale async completions must not unlock its successor.
const directCanvasOwnerId = ref('')
const directCanvasOwned = computed(() => Boolean(directCanvasOwnerId.value))
// A restored cloud canvas cannot subscribe from an old cursor until a latest
// checkpoint has established its playback floor. Retain this job-scoped gate
// on failure so retry resumes the same owner without reopening historical SSE.
const directCanvasRecoveryJobId = ref('')
const uncertainCanvasCreation = shallowRef(null)
// During a parent→child handoff the editor is already fenced by the child,
// while the dialog retains the parent owner until the child's latest checkpoint
// is known. Teardown must detach the actual editor owner in that interval.
let pendingHandoffCanvasJobId = ''
let directTerminalTargetJobId = ''
const submissionStartedAt = ref(0)
const runningPrompt = ref('')
const runningMessageRoute = ref('current')
const cancelling = ref(false)
const cancelConfirming = ref(false)
const downloading = ref(false)
const savingCloud = ref(false)
const applying = ref(false)
const rejectingReview = ref(false)
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
const pendingFollowupPrompt = ref('')
const retryPrompt = ref('')
const composerInputRef = ref(null)
const selectedNodeUids = ref([])
const sourceContext = ref(null)
const editorContext = ref(null)
const sourceFingerprint = ref('')
const sourceBaselineMismatch = ref(false)
const sourceFileInputRef = ref(null)
const activityTimelineRef = ref(null)
const proposalConfirmationRef = ref(null)
const proposalReviewRef = ref(null)
const livePreviewNoticeRef = ref(null)
const uploadedFileName = ref('')
const uploadedFileArtifact = ref(null)
const agentEvents = ref([])
const draftDocument = shallowRef(null)
const realtimeConnectionState = ref('idle')
const realtimeError = ref('')
const draftFreshness = ref('idle')
const draftFreshnessMessage = ref('')
const livePreviewRecovering = ref(false)
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
let terminalHydrationGeneration = 0
let terminalFinalizationState = null
const selectedArtifactLoading = ref(false)
const showAdvancedSettings = ref(false)
const discussionMode = ref(false)
const livePreviewActive = ref(false)
const livePreviewPaused = ref(false)
const livePreviewReverting = ref(false)
const livePreviewRevertingJobId = ref('')
const livePreviewAutoAccepting = ref(false)
const livePreviewError = ref('')
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
const livePreviewRenderedVersion = ref(-1)
const latestPreviewEpoch = ref(1)
const livePreviewFramesPending = ref(false)
const livePreviewRendering = ref(false)
const livePreviewRenderedNodeCount = ref(0)
const livePreviewTargetNodeCount = ref(0)
const livePreviewChangeSummary = ref(null)
const livePreviewAccessibleAnnouncement = ref('')
const generationClockNow = ref(Date.now())
// Keep the canvas moving at roughly 14 fps. The editor still coalesces newer
// server snapshots, while the shorter cadence removes the visible stop-start
// feeling caused by 120ms gaps between otherwise small preview frames.
// A short cadence makes character frames feel like a normal agent stream while
// still yielding between SVG updates so the canvas remains responsive.
const LIVE_PREVIEW_FRAME_INTERVAL_MS = 56
const LIVE_PREVIEW_ANNOUNCEMENT_INTERVAL_MS = 1800
let pollTimer = null
let pollController = null
let draftController = null
let livePreviewFlushPromise = Promise.resolve()
let livePreviewRevertPromise = Promise.resolve(true)
let livePreviewFlushTimer = null
let livePreviewAutoAcceptTimer = null
let livePreviewAutoAcceptPromise = null
let livePreviewDirectSettlePromise = null
let livePreviewDirectSettleJobId = ''
const livePreviewAutoAcceptFailedJobId = ref('')
let livePreviewPendingFrame = null
let livePreviewOldestPendingAt = null
let livePreviewFlushInFlight = false
let livePreviewEditorStarted = false
let livePreviewRenderedDocument = null
let livePreviewBaselineDocument = null
let livePreviewGeneration = 0
let livePreviewJobId = ''
let livePreviewRevertFailedJobId = ''
let livePreviewSuppressedJobId = ''
let livePreviewApplyingJobId = ''
let livePreviewAnnouncementTimer = null
let livePreviewAnnouncementPending = ''
let livePreviewAnnouncementLastAt = 0
let realtimeController = null
let realtimeReconnectTimer = null
let localAckRetryTimer = null
let restoreController = null
let requestedTaskSequence = 0
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
let monitoringSuspendedJobId = ''
let componentAlive = true
let submitAttempt = null
let saveCloudAttempt = null
let followupAttempt = null
let retryAttempt = null
let queueAttempt = null
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
const LIVE_PREVIEW_SUPPRESSION_STORAGE_KEY = 'MINDMAP_AI_LIVE_PREVIEW_SUPPRESSION_V1'
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
const generationModeOptions = Object.freeze([
  { value: 'dfs_stream', label: '流式深度', hint: '逐分支构建，实时看到每个分支成形' },
  { value: 'bfs_stream', label: '流式广度', hint: '逐层构建，实时看到每一层展开' },
  { value: 'balanced', label: '均衡', hint: '分批构建，兼顾过程呈现与总耗时' },
  { value: 'complete', label: '完整', hint: '不限制批次节奏，最快得到完整结果' },
])
const GENERATION_MODE_VALUES = new Set(generationModeOptions.map(item => item.value))
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
  generationMode: 'balanced',
  maxNodes: 100,
  maxDepth: 6,
})

const terminalStatuses = new Set([
  'ready', 'applied', 'undone', 'completed_file', 'completed_direct', 'completed_no_change',
  'completed_message',
  'needs_review', 'stale', 'cancelled', 'failed', 'expired',
  'needs_input', 'rejected',
])
function isDirectExecutionJob(candidate = job.value) {
  return candidate?.executionMode === 'direct'
}

const retryableStatuses = new Set(['failed', 'cancelled', 'expired', 'stale'])
const running = computed(() => Boolean(job.value && !terminalStatuses.has(job.value.status)))
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
  || rejectingReview.value
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
const generationModeHint = computed(() => (
  generationModeOptions.find(item => item.value === form.generationMode)?.hint
  || '分批构建，兼顾过程呈现与总耗时'
))
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
const starterItems = computed(() => {
  const hasEditor = Boolean(editorContext.value?.document?.root)
  const hasSelection = selectedNodeUids.value.length > 0
  if (!hasEditor) {
    return [
      { type: 'topic', label: '从一个主题开始搭建脑图' },
      { type: 'outline', label: '先列出这个主题的主要分支' },
      { type: 'question', label: '和我一起讨论脑图结构' },
    ]
  }
  if (editorReadonly.value) {
    return [
      { type: 'analyze', label: '分析这张图的结构和重点' },
      { type: 'gaps', label: '找出当前脑图的缺口' },
      { type: 'duplicates', label: '检查重复、冲突和遗漏' },
    ]
  }
  return [
    { type: 'analyze', label: hasSelection ? '分析当前分支' : '分析这张图' },
    { type: 'supplement', label: hasSelection ? '补充当前分支' : '补充薄弱分支' },
    { type: 'duplicates', label: '检查重复、冲突和遗漏' },
  ]
})
const composerText = computed({
  get() {
    if (!job.value) return form.prompt
    if (running.value) return runningPrompt.value
    if (retryAvailable.value) return retryPrompt.value
    if (followupAvailable.value) return followupPrompt.value
    return ''
  },
  set(value) {
    if (!job.value) form.prompt = value
    else if (running.value) runningPrompt.value = value
    else if (retryAvailable.value) retryPrompt.value = value
    else if (followupAvailable.value) followupPrompt.value = value
  },
})
const composerEnabled = computed(() => Boolean(
  !actionBusy.value
  && (running.value || !livePreviewCanvasMutationBlocked.value)
  && (!job.value || running.value || retryAvailable.value || followupAvailable.value)
))
const composerPlaceholder = computed(() => {
  if (running.value) {
    return messageModeActive.value
      ? '继续输入，按 ⌘/Ctrl + Enter 排到下一轮…'
      : '继续告诉 AI 要怎么改，按 ⌘/Ctrl + Enter 排到下一轮…'
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
const composerPreflightText = computed(() => {
  if (running.value) return ''
  if (messageModeActive.value || discussionMode.value) {
    return form.sourceMode === 'current'
      ? '只讨论当前脑图，不会修改画布。'
      : '只返回文字回答，不会修改当前画布。'
  }
  if (form.sourceMode === 'new' || form.sourceMode === 'file') {
    return '将生成独立脑图；当前画布保持不变，结果完成后可另存或打开。'
  }
  if (
    form.sourceMode === 'current'
    && (sourceContext.value?.mindmapId || editorContext.value?.mindmapId)
    && !editorReadonly.value
  ) {
    return form.scopeType === 'document'
      ? 'AI 会通过受控工具直接写入云端正文，并实时同步到协作者；离开页面后任务仍会继续。'
      : 'AI 只会通过受控工具直接写入授权范围，并实时同步到协作者；离开页面后任务仍会继续。'
  }
  if (form.scopeType === 'branch') return '只读取并编辑当前分支；结果会实时显示在当前画布。'
  if (form.scopeType === 'selectedNodes') {
    return `只读取并编辑已选 ${selectedNodeUids.value.length} 个节点及其子树；结果会实时显示在当前画布。`
  }
  return '将读取整张当前脑图并实时编辑当前画布；完成后结果默认保留，可撤销本轮。'
})
const composerCanSend = computed(() => Boolean(
  composerEnabled.value
  && composerText.value.trim()
  && !restoreError.value
  && selectedAgentReady.value
))
const livePreviewCatchingUp = computed(() => {
  const received = Number(latestPreviewVersion.value)
  const rendered = Number(livePreviewRenderedVersion.value)
  return Boolean(
    livePreviewActive.value
    && (
      livePreviewFramesPending.value
      || (
        Number.isSafeInteger(received)
        && received >= 0
        && (!Number.isSafeInteger(rendered) || rendered < received)
      )
    )
  )
})
const livePreviewNodeProgress = computed(() => {
  const rendered = Number(livePreviewRenderedNodeCount.value)
  const target = Number(livePreviewTargetNodeCount.value)
  if (!livePreviewActive.value || !Number.isSafeInteger(rendered) || rendered < 1
    || !Number.isSafeInteger(target) || target < 1) return ''
  if (rendered === target) return `当前画布已显示 ${rendered} 个节点。`
  if (rendered < target) return `当前画布已显示 ${rendered} / ${target} 个节点。`
  return `当前画布已显示 ${rendered} 个节点，正在收敛到 ${target} 个节点。`
})
function formatLivePreviewChangeSummary(summary) {
  if (!summary || typeof summary !== 'object') return ''
  const parts = [
    Number(summary.added) > 0 ? `新增 ${Number(summary.added)}` : '',
    Number(summary.updated) > 0 ? `修改 ${Number(summary.updated)}` : '',
    Number(summary.moved) > 0 ? `移动 ${Number(summary.moved)}` : '',
    Number(summary.deleted) > 0 ? `删除 ${Number(summary.deleted)}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}
const livePreviewChangeSummaryText = computed(() => (
  formatLivePreviewChangeSummary(livePreviewChangeSummary.value)
))
const livePreviewNoticeTitle = computed(() => {
  if (livePreviewAutoAccepting.value) return '正在保存 AI 结果'
  if (livePreviewAutoAcceptFailedJobId.value === String(job.value?.id || '')) return 'AI 结果仍在画布，保存未完成'
  if (applying.value) return '正在保存当前 AI 预览'
  if (cancelling.value && livePreviewActive.value) return '正在停止，保存已生成结果'
  if (livePreviewReverting.value) return '正在撤回 AI 实时预览'
  if (cancelling.value) return '正在停止 AI 任务'
  if (realtimeConnectionState.value === 'offline') return '实时连接已中断，已保留当前预览'
  if (realtimeConnectionState.value === 'reconnecting') return '正在恢复实时预览'
  if (livePreviewPausedVisible.value) return '已暂停 AI 实时显示'
  if (livePreviewRendering.value) return '正在绘制 AI 实时结果'
  if (running.value) return 'AI 正在当前画布实时预览'
  if (highImpactReviewRequired.value) return 'AI 结果等待确认'
  return livePreviewCatchingUp.value ? '正在完成 AI 画布预览' : 'AI 结果已在当前画布预览'
})
const livePreviewNoticeDescription = computed(() => {
  const received = Number(latestPreviewVersion.value)
  const rendered = Number(livePreviewRenderedVersion.value)
  const renderedStep = Number.isSafeInteger(rendered) && rendered >= 0 ? `已显示第 ${rendered} 步。` : ''
  const catchup = livePreviewCatchingUp.value && Number.isSafeInteger(received)
    ? `正在平滑补齐最新结果（已收到第 ${received} 步）。`
    : ''
  const nodeProgress = livePreviewNodeProgress.value
  const changeSummary = livePreviewChangeSummaryText.value
    ? `本次变更：${livePreviewChangeSummaryText.value}。`
    : ''
  if (livePreviewAutoAccepting.value) {
    return `${renderedStep}${changeSummary}${catchup}生成已完成，正在保存当前画布结果；完成后可随时撤销本次 AI 操作。`
  }
  if (livePreviewAutoAcceptFailedJobId.value === String(job.value?.id || '')) {
    return `${renderedStep}${changeSummary}${nodeProgress}当前结果已保留，可重试保存或撤销本次 AI 操作。`
  }
  if (applying.value) return `${renderedStep}${changeSummary}${catchup}正在完成校验与保存，当前画布会保持不变。`
  if (cancelling.value && livePreviewActive.value) {
    return `${renderedStep}${changeSummary}正在停止 AI 任务，已生成内容会继续保留并保存。`
  }
  if (livePreviewReverting.value) {
    return `${renderedStep}${changeSummary}正在撤回当前画布预览，完成后恢复原内容。`
  }
  if (cancelling.value) {
    return `${renderedStep}${changeSummary}正在停止 AI 任务，等待服务端确认最后修改。`
  }
  if (['offline', 'reconnecting'].includes(realtimeConnectionState.value)) {
    return `${renderedStep}${changeSummary}${nodeProgress}当前画面保持不变，连接恢复后会继续接收 AI 结果。`
  }
  if (livePreviewPausedVisible.value) {
    return `${renderedStep}${changeSummary}${nodeProgress}当前画面保持不变，AI 仍在后台生成；点击“继续显示”后会平滑补齐。`
  }
  if (livePreviewRendering.value) {
    return `${renderedStep}${changeSummary}${nodeProgress}正在把当前帧绘制到画布，完成后继续接收下一帧。`
  }
  if (!running.value && livePreviewCatchingUp.value) {
    return `${renderedStep}${changeSummary}${nodeProgress}${catchup}任务已完成，画布正在显示最后的变更。`
  }
  if (highImpactReviewRequired.value) {
    return `${renderedStep}${changeSummary}${nodeProgress}本次包含较大结构变更，请查看差异后明确采纳；也可以撤销本轮修改。`
  }
  return running.value
    ? `${renderedStep}${changeSummary}${nodeProgress}${catchup}画布会随生成过程继续更新，完成后会自动保存当前结果。`
    : `${renderedStep}${changeSummary}${nodeProgress}结果已完成并保存到当前脑图；如需恢复上一版本，可撤销本次 AI 全部操作。`
})
const selectedTurn = computed(() => (
  sessionTurns.value.find(turn => String(turn?.job?.id || '') === selectedTurnJobId.value)
  || null
))
const conversationTurns = computed(() => buildMindmapAiConversationTurns({
  sessionTurns: sessionTurns.value,
  currentJob: job.value,
  events: agentEvents.value,
}).map(turn => ({
  ...turn,
  tagSuggestions: collectMindmapAiTagSuggestions(turn.events, turn.job.id),
})))
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
    && (
      ['applied', 'undone'].includes(candidate?.status)
      || candidate?.status === 'completed_direct'
    )
  ) return candidate
  return candidate?.artifactId
    && ['ready', 'completed_file', 'completed_no_change'].includes(candidate.status)
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
  && !livePreviewCanvasMutationBlocked.value
))
const taskConfigurationLocked = computed(() => restoringJob.value || Boolean(job.value))
const agentSelectionLocked = computed(() => (
  restoringJob.value
  || submitting.value
  || continuing.value
  || retrying.value
  || livePreviewCanvasMutationBlocked.value
  || (Boolean(job.value) && !followupAvailable.value && !retryAvailable.value)
))
const editorReadonly = computed(() => Boolean(props.readonly || editorContext.value?.readonly))
const livePreviewEligible = computed(() => Boolean(
  !messageModeActive.value
  && form.sourceMode === 'current'
  // Follow-up jobs temporarily clear sourceContext.document while the server
  // revalidates the cloud baseline. The editor context is that same validated
  // current document and keeps live preview available during this handoff.
  && (sourceContext.value?.document?.root || editorContext.value?.document?.root)
  && !viewingHistoricalArtifact.value
  && !props.readonly
  && sourceContext.value?.readonly !== true
  && !sourceBaselineMismatch.value
  && livePreviewSuppressedJobId !== String(job.value?.id || '')
  && !['applied', 'undone', 'cancelled', 'failed', 'expired', 'stale'].includes(job.value?.status)
))
const directExecutionNoticeVisible = computed(() => Boolean(
  isDirectExecutionJob()
  && !messageModeActive.value
  && job.value?.id
  && (
    running.value
    || job.value.status === 'completed_direct'
    || job.value.status === 'completed_no_change'
  )
))
const directExecutionNoticeTitle = computed(() => {
  if (job.value?.status === 'completed_direct') return 'AI 已直接更新云端脑图'
  if (job.value?.status === 'completed_no_change') return 'AI 已完成检查，脑图没有变化'
  return 'AI 正在后台编辑云端脑图'
})
const directExecutionNoticeDescription = computed(() => {
  if (job.value?.status === 'completed_direct') {
    return '修改已经写入云端正文并通过协作通道同步；即使关闭当前页面，任务也不会中断。'
  }
  if (job.value?.status === 'completed_no_change') {
    return '本轮没有需要写入的内容；任务已结束，当前脑图保持不变。'
  }
  return 'Agent 正在通过受控脑图工具直接写入云端正文；你可以离开页面，任务会在服务端继续执行。'
})
const livePreviewNoticeVisible = computed(() => Boolean(
  livePreviewActive.value
  || (
    livePreviewReverting.value
    && livePreviewRevertingJobId.value
    && livePreviewRevertingJobId.value === String(job.value?.id || '')
  )
))
const livePreviewPlaybackAvailable = computed(() => Boolean(
  livePreviewActive.value
  && livePreviewJobId
  && livePreviewJobId === String(job.value?.id || '')
  && (running.value || livePreviewCatchingUp.value)
  && !actionBusy.value
  && !livePreviewReverting.value
))
const livePreviewCanvasMutationBlocked = computed(() => Boolean(
  livePreviewActive.value || livePreviewReverting.value || preparingCanvas.value || directCanvasOwned.value
))
const livePreviewPausedVisible = computed(() => Boolean(
  livePreviewPaused.value && livePreviewPlaybackAvailable.value
))
const livePreviewPreparing = computed(() => Boolean(
  running.value
  && livePreviewEligible.value
  && !livePreviewActive.value
  && !cancelling.value
  && job.value?.status !== 'cancel_requested'
))
const livePreviewPreparingTitle = computed(() => (
  job.value?.status === 'waiting_turn'
    ? '下一轮已排队'
    : ['queued', 'preparing'].includes(job.value?.status)
      ? 'AI 正在准备实时画布'
      : 'AI 正在生成首个节点'
))
const livePreviewPreparingDescription = computed(() => {
  if (job.value?.status === 'waiting_turn') return '到达安全边界后会自动继续，不需要重新提交。'
  const startedAt = Date.parse(job.value?.createdTime || '')
  const elapsed = Number.isFinite(startedAt)
    ? `已运行 ${Math.max(0, Math.floor((generationClockNow.value - startedAt) / 1_000))} 秒。`
    : ''
  return `${elapsed}首个变化出现后会立即显示在当前画布，生成期间可以随时停止任务。`
})
const livePreviewRecoveryAvailable = computed(() => Boolean(
  job.value?.id
  && !messageModeActive.value
  && !isTerminalStatus(job.value?.status)
  && ['stale', 'unavailable', 'restarted'].includes(draftFreshness.value)
  && realtimeConnectionState.value !== 'offline'
  && !sourceBaselineMismatch.value
  && !actionBusy.value
))

function clearLivePreviewAnnouncement() {
  clearTimeout(livePreviewAnnouncementTimer)
  livePreviewAnnouncementTimer = null
  livePreviewAnnouncementPending = ''
  livePreviewAnnouncementLastAt = 0
  livePreviewAccessibleAnnouncement.value = ''
}

function queueLivePreviewAnnouncement(title, description, force = false) {
  const message = [title, description].filter(Boolean).join('。')
  if (!message) return
  livePreviewAnnouncementPending = message
  if (force) {
    clearTimeout(livePreviewAnnouncementTimer)
    livePreviewAnnouncementTimer = null
  } else if (livePreviewAnnouncementTimer) {
    return
  }
  const elapsed = Date.now() - livePreviewAnnouncementLastAt
  const delay = force
    ? 0
    : Math.max(0, LIVE_PREVIEW_ANNOUNCEMENT_INTERVAL_MS - elapsed)
  livePreviewAnnouncementTimer = setTimeout(() => {
    livePreviewAccessibleAnnouncement.value = livePreviewAnnouncementPending
    livePreviewAnnouncementPending = ''
    livePreviewAnnouncementLastAt = Date.now()
    livePreviewAnnouncementTimer = null
  }, delay)
}

watch(
  [
    livePreviewPreparing,
    livePreviewPreparingTitle,
    livePreviewPreparingDescription,
    livePreviewNoticeVisible,
    livePreviewNoticeTitle,
    livePreviewNoticeDescription,
  ],
  (next, previous = []) => {
    const [preparing, preparingTitle, preparingDescription, active, title, description] = next
    if (!preparing && !active) {
      clearLivePreviewAnnouncement()
      return
    }
    const previousPreparing = previous[0]
    const previousTitle = previous[0] === true ? previous[1] : previous[4]
    const announcementTitle = preparing ? preparingTitle : title
    const announcementDescription = preparing ? preparingDescription : description
    queueLivePreviewAnnouncement(
      announcementTitle,
      announcementDescription,
      preparing !== previousPreparing || announcementTitle !== previousTitle,
    )
  },
)
const canRejectLiveDraft = computed(() => Boolean(
  livePreviewActive.value
  && !isDirectExecutionJob()
  && !viewingHistoricalArtifact.value
  && !actionBusy.value
  && job.value?.id
  && !['applied', 'undone', 'rejected'].includes(job.value.status)
  && !highImpactReviewRequired.value
))
const canApplyLiveCanvasDraft = computed(() => Boolean(
  livePreviewActive.value
  && canApplyCurrentProposal.value
  && diffConfirmed.value
  && !livePreviewCatchingUp.value
  && !livePreviewPreparing.value
  && !actionBusy.value
  && !editorReadonly.value
))
const canUndoCurrentProposal = computed(() => Boolean(
  !viewingHistoricalArtifact.value
  &&
  job.value?.proposalId
  && ['applied', 'completed_direct', 'failed', 'stale', 'cancelled'].includes(job.value.status)
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
const nativeModelConfigurationIssue = computed(() => {
  if (form.agentKey !== 'native_mindmap') return ''
  const model = models.value.find(item => String(item.modelId) === String(form.modelId))
  if (!model) return ''
  if (
    model.provider === 'Anthropic'
    && /\/compatible-mode\//i.test(String(model.baseUrl || ''))
  ) {
    return '当前模型使用兼容模式接口，但提供商选了 Anthropic。请在 AI 模型管理中改为 DashScope 或 OpenAI，并填写实际模型编码；也可改选 Ollama 模型。'
  }
  return ''
})
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
  if (nativeModelConfigurationIssue.value) return nativeModelConfigurationIssue.value
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
// Direct-write rounds do not create a normal Proposal impact payload.  Prefer
// the newer counter schema, then the terminal direct_completed event over a
// same-schema proposal read; fall back to per-batch commit metadata
// for older tasks.  This keeps the result card from showing four misleading
// zeros simply because the legacy `{ direct: true }` marker had no counters.
const resultImpactForDisplay = computed(() => {
  if (!proposal.value) return null
  if (!isDirectExecutionJob()) return proposal.value.impact || null
  return directImpactForMindmapAiResult(proposal.value, resolveMindmapAiDirectChangeSummary({
    proposal: proposal.value,
    events: agentEvents.value,
    jobId: job.value?.id,
  }))
})
const resultImpactSummaryAvailable = computed(() => {
  const impact = resultImpactForDisplay.value
  if (!impact) return false
  return ['createdCount', 'updatedCount', 'movedCount', 'deletedCount'].every(key => {
    const count = Number(impact[key])
    return Number.isSafeInteger(count) && count >= 0
  })
})
const canApplyCurrentProposal = computed(() => Boolean(
  !viewingHistoricalArtifact.value
  && !messageModeActive.value
  && !sourceBaselineMismatch.value
  && currentProposalSourceAvailable.value
  && job.value?.proposalId
  && (
    job.value.status === 'ready'
    || (
      job.value.status === 'needs_review'
      && proposal.value?.impact?.highImpact === true
    )
  )
))
const highImpactReviewRequired = computed(() => Boolean(
  !viewingHistoricalArtifact.value
  && !messageModeActive.value
  && job.value?.status === 'needs_review'
  && proposal.value?.impact?.highImpact === true
))
const proposalReviewFinalized = computed(() => Boolean(
  proposal.value
  && ['applied', 'undone', 'rejected'].includes(job.value?.status)
))
const jobStatusLabels = {
  queued: '任务已排队',
  waiting_turn: '已收到，等待上一轮结果确认保存',
  preparing: '正在准备安全上下文',
  running: 'Agent 正在构建脑图',
  validating: '正在校验 SMM v2',
  cancel_requested: '正在停止',
  ready: '结果已就绪',
  applied: '已应用',
  undone: '已撤销',
  completed_file: '已保存为云端脑图',
  completed_direct: 'AI 已直接更新云端脑图',
  completed_message: 'AI 已回复',
  completed_no_change: '未发现需要应用的变化',
  cancelled: '任务已取消',
  failed: '任务失败',
  expired: '结果已过期',
  stale: '基线已过期',
  needs_review: '需要人工确认',
  rejected: '已拒绝本轮变更',
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
  if (job.value?.status === 'waiting_turn') return '等待上一轮结果确认保存'
  if (livePreviewPausedVisible.value) return '已暂停显示'
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
const jobActivitySummary = computed(() => {
  if (job.value?.status === 'waiting_turn') {
    const queueEvent = [...agentEvents.value].reverse().find(event => (
      event.jobId === job.value.id
      && event.eventType === 'job_created'
      && Number.isSafeInteger(Number(event.payload?.queuePosition))
    ))
    const queuePosition = queueEvent?.payload?.queuePosition
    if (queueEvent?.payload?.route === 'current') {
      return '已加入当前任务 · 等待下一个安全边界'
    }
    return Number(queuePosition) > 1
      ? `已排入下一轮 · 前方还有 ${Number(queuePosition) - 1} 条要求`
      : '已排入下一轮，上一轮结果确认保存后自动开始'
  }
  if (running.value) {
    const startedAt = Date.parse(job.value?.createdTime || '')
    const elapsed = Number.isFinite(startedAt)
      ? ` · 已运行 ${Math.max(0, Math.floor((generationClockNow.value - startedAt) / 1_000))} 秒`
      : ''
    if (livePreviewRenderedNodeCount.value > 0) {
      return `已在画布显示 ${livePreviewRenderedNodeCount.value} 个节点${elapsed}`
    }
    return `${statusLabel.value}${elapsed}`
  }
  if (livePreviewChangeSummaryText.value) return `本轮${livePreviewChangeSummaryText.value}`
  if (job.value?.status === 'rejected') return '高影响变更未采纳，当前脑图保持原内容'
  if (['ready', 'applied', 'completed_file'].includes(job.value?.status)) return '结果已保存，可撤销本轮 AI 修改'
  if (job.value?.status === 'completed_direct') return 'AI 已完成后台直写，当前页面会自动同步最新内容'
  if (job.value?.status === 'completed_message') return '回答已完成'
  return statusLabel.value
})

function isHttpNotFound(error) {
  return Number(error?.response?.status ?? error?.status) === 404
}

function isDefinitiveAiCreationRejection(error) {
  const status = Number(error?.response?.status ?? error?.status)
  if ([400, 401, 403, 404, 405, 413, 422, 429].includes(status)) return true
  // Business codes alone cannot establish absence: the server may have
  // committed already or failed to verify the key after an exception.
  return error?.data?.creationRejected === true || error?.response?.data?.data?.creationRejected === true
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

function readLivePreviewSuppression(jobId) {
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId || !jobId) return false
  try {
    const stored = JSON.parse(
      readMindmapAiOwnerSessionItem(LIVE_PREVIEW_SUPPRESSION_STORAGE_KEY, ownerUserId) || 'null',
    )
    return stored?.ownerUserId === ownerUserId
      && String(stored.jobId || '') === String(jobId)
      && Number.isFinite(Number(stored.suppressedAt))
      && Date.now() - Number(stored.suppressedAt) <= STORED_JOB_TTL_MS
  } catch {
    return false
  }
}

function persistLivePreviewSuppression(jobId) {
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId || !jobId) return false
  return writeMindmapAiOwnerSessionItem(
    LIVE_PREVIEW_SUPPRESSION_STORAGE_KEY,
    ownerUserId,
    JSON.stringify({ ownerUserId, jobId: String(jobId), suppressedAt: Date.now() }),
  )
}

function currentAiOwnerUserId() {
  return normalizeNumericOwnerUserId(userStore.id)
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
  return sha256Hex(bytes)
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
    generationMode: GENERATION_MODE_VALUES.has(overrides.generationMode)
      ? overrides.generationMode
      : form.generationMode,
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
    'language', 'layout', 'density', 'generationMode', 'maxNodes', 'maxDepth',
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
  const generationMode = GENERATION_MODE_VALUES.has(stored.generationMode)
    ? stored.generationMode
    : (GENERATION_MODE_VALUES.has(snapshot.generationMode) ? snapshot.generationMode : 'balanced')
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
  form.generationMode = generationMode
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
  if (sourceContext.value.document?.root && !isDirectExecutionJob(snapshot)) {
    draftDocument.value = cloneRuntimeValue(sourceContext.value.document)
  } else if (isDirectExecutionJob(snapshot)) {
    draftDocument.value = null
  }
}

async function reconcileRestoredSourceBaseline(snapshot, saved = {}) {
  sourceBaselineMismatch.value = false
  // A direct job advances its own cloud revision on every accepted tool call.
  // Comparing that revision to its original base mistakes its own work for a
  // conflict and disables playback after reopening the editor.
  if (isDirectExecutionJob(snapshot)) return true
  if (![
    'waiting_turn', 'queued', 'preparing', 'running', 'validating', 'cancel_requested',
    'ready', 'needs_review',
  ].includes(snapshot?.status)) return true
  const sourceType = saved.sourceType || snapshot?.sourceType
  let mismatch = false
  if (sourceType === 'cloud_document') {
    const expectedRevision = Number(snapshot?.baseRevision ?? saved.sourceRevision)
    const currentRevision = Number(editorContext.value?.revision)
    mismatch = Number.isSafeInteger(expectedRevision)
      && expectedRevision > 0
      && Number.isSafeInteger(currentRevision)
      && currentRevision > 0
      && expectedRevision !== currentRevision
  } else if (sourceType === 'local_snapshot') {
    const expectedFingerprint = String(snapshot?.baseHash || saved.sourceFingerprint || '')
    if (expectedFingerprint && editorContext.value?.document?.root) {
      const currentFingerprint = await computeMindmapSnapshotFingerprint(editorContext.value.document)
      mismatch = currentFingerprint !== expectedFingerprint
    }
  }
  if (!mismatch) return true
  sourceBaselineMismatch.value = true
  draftFreshness.value = 'stale'
  draftFreshnessMessage.value = '当前脑图已在任务开始后发生变化，已停止自动实时预览；请基于最新内容重新生成。'
  return false
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
  if (turnJob.status === 'cancelled') {
    const cancellationReason = String(turnJob.errorMessage || turnJob.error_message || '').trim()
    return cancellationReason || '本轮任务已取消。'
  }
  if (turnJob.status === 'rejected') return '本轮高风险 AI 变更未采纳，当前脑图保持原内容。'
  if (turnJob.status === 'expired') return '本轮结果已过期，可以基于原要求重新生成。'
  if (turnJob.status === 'stale' && turnJob.errorCode === 'AI_DOCUMENT_CONFLICT') {
    return 'AI 直写过程中检测到协作者或其他窗口更新，已停止后续写入；请基于当前云端内容重新开始。'
  }
  if (turnJob.status === 'needs_review') return '脑图草稿已生成，仍有部分内容需要人工确认。'
  if (turnJob.status === 'waiting_turn') {
    const queueEvent = [...(turn?.events || [])].reverse().find(event => (
      event?.eventType === 'job_created'
      && Number.isSafeInteger(Number(event?.payload?.queuePosition))
    ))
    if (queueEvent?.payload?.route === 'current') {
      return '已加入当前任务，将在下一个安全边界采用。'
    }
    const queuePosition = queueEvent?.payload?.queuePosition
    return Number(queuePosition) > 1
      ? `已收到你的下一条要求，前方还有 ${Number(queuePosition) - 1} 条要求。`
      : '已收到你的下一条要求，上一轮结果确认保存后会自动开始。'
  }
  if (turnJob.status === 'completed_no_change') return '已完成分析，当前脑图不需要应用新的结构变化。'
  if (turnJob.status === 'completed_direct') return 'AI 已完成后台直写，当前脑图会自动同步最新内容。'
  if (['ready', 'applied', 'undone', 'completed_file'].includes(turnJob.status)) {
    const completedEvent = [...(turn?.events || [])].reverse().find(event => (
      event?.eventType === 'agent_completed'
    ))
    const nodeCount = Number(completedEvent?.payload?.summary?.nodeCount)
    const title = String(turnJob.title || '脑图结果').trim()
    return Number.isFinite(nodeCount)
      ? `${title}已生成，共 ${nodeCount} 个节点。`
      : `${title}已生成，当前画布已展示最新结果，可以检查差异。`
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
    message_received: '消息已接收',
    queue_reparented: '队列已调整',
    agent_error: 'Agent 异常',
    tool_started: '工具开始',
    tool_completed: '工具完成',
    tool_failed: '工具失败',
    tool_plan_received: '执行计划',
    tool_plan_failed: '计划失败',
    tag_suggestions: '标签建议',
    artifact_ready: '结果就绪',
    artifact_needs_review: '等待审核',
    artifact_no_change: '无内容变化',
    direct_completed: '云端直写完成',
    cancel_requested: '取消请求',
    local_applied: '本地应用',
    local_undone: '本地撤销',
    cloud_file_created: '云端文件',
    cloud_applied: '云端应用',
    cloud_undone: '云端撤销',
    proposal_stale: '提案过期',
    proposal_rejected: '提案未采纳',
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
    read_document_detail: '读取脑图详情',
    get_node_tags: '读取节点标签',
    search_tags: '检索已有标签',
    suggest_tags: '提出标签建议',
    edit_node_text: '编辑节点文本',
    edit_node_tags: '编辑节点标签',
    add_comment: '添加脑图评论',
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
    if (payload.route === 'current') {
      return '已加入当前任务，将在下一个安全边界采用'
    }
    if (payload.route === 'next' && Number.isSafeInteger(Number(payload.queuePosition))) {
      const position = Number(payload.queuePosition)
      return position > 1
        ? `已排入下一轮 · 前方还有 ${position - 1} 条要求`
      : '已排入下一轮，上一轮结果确认保存后自动开始'
    }
    return Number.isSafeInteger(turnIndex) && turnIndex > 1
      ? `已创建第 ${turnIndex} 轮任务`
      : '已创建 AI 脑图任务'
  }
  if (event?.eventType === 'agent_progress') return describeMindmapAiAgentProgress(payload)
  if (event?.eventType === 'tag_suggestions') return '已提出标签建议，尚未创建或绑定；可手动创建后在下一轮引用'
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
  if (event?.eventType === 'artifact_ready') return payload.completionReason === 'stopped'
    ? '任务已停止，已保存当前生成结果'
    : '结果文件与提案已通过校验'
  if (event?.eventType === 'artifact_needs_review') return '结果已生成，部分内容需要人工确认'
  if (event?.eventType === 'artifact_no_change') return '校验完成，没有发现需要应用的变化'
  if (event?.eventType === 'direct_completed') {
    const count = Number(payload.operationCount)
    return Number.isSafeInteger(count)
      ? `已直接写入云端脑图 · ${count} 个操作`
      : '已直接写入云端脑图并同步权威版本'
  }
  if (event?.eventType === 'cancel_requested') return '已收到取消请求，正在安全停止 Agent'
  if (event?.eventType === 'local_applied') return '提案已应用到当前本地脑图'
  if (event?.eventType === 'local_undone') return '本地 AI 提案已安全撤销'
  if (event?.eventType === 'cloud_file_created') return '结果已另存为新的云端脑图'
  if (event?.eventType === 'cloud_applied') return '提案已应用到云端脑图并同步权威版本'
  if (event?.eventType === 'cloud_undone') return '云端 AI 提案已安全撤销'
  if (event?.eventType === 'proposal_stale') return '脑图基线已经变化，该提案需要重新生成'
  if (event?.eventType === 'proposal_rejected') return '本轮高风险 AI 变更未采纳，已恢复生成前内容'
  if (['agent_error', 'stream_error'].includes(event?.eventType)) return '运行发生异常，详情请查看任务状态'
  return '已记录一条经过清洗的运行审计事件'
}

function clearStoredActiveJob() {
  clearMindmapAiOwnerSessionItem(ACTIVE_JOB_STORAGE_KEY, currentAiOwnerUserId())
}

function clearStoredRecentJob() {
  clearMindmapAiOwnerSessionItem(RECENT_JOB_STORAGE_KEY, currentAiOwnerUserId())
}

function clearAgentRuntimeState() {
  terminalFinalizationState?.controller?.abort()
  terminalFinalizationState = null
  agentEvents.value = []
  agentEventKeys.clear()
  agentEventEnvelopeKeys.clear()
  jobEventSequences.clear()
  draftDocument.value = null
  sourceBaselineMismatch.value = false
  latestEventSequence.value = 0
  latestPreviewVersion.value = -1
  latestPreviewEpoch.value = 1
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
  terminalHydrationGeneration += 1
  terminalHydrationRetryCount = 0
  clearTimeout(terminalHydrationRetryTimer)
  terminalHydrationRetryTimer = null
  livePreviewRenderedVersion.value = -1
  livePreviewFramesPending.value = false
  livePreviewRendering.value = false
  livePreviewPaused.value = false
  livePreviewRenderedNodeCount.value = 0
  livePreviewTargetNodeCount.value = 0
  livePreviewChangeSummary.value = null
  livePreviewAutoAcceptFailedJobId.value = ''
  clearTimeout(livePreviewAutoAcceptTimer)
  livePreviewAutoAcceptTimer = null
  livePreviewAutoAccepting.value = false
  runningMessageRoute.value = 'current'
  clearLivePreviewAnnouncement()
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

function resetNewJob({ clearStoredJob = true, preserveForm = true, detach = false } = {}) {
  if (!detach && (running.value || preparingCanvas.value || directCanvasOwned.value
    || livePreviewActive.value || livePreviewReverting.value)) return false
  if (detach) {
    const ownerId = pendingHandoffCanvasJobId || directCanvasOwnerId.value || uncertainCanvasCreation.value?.preparationId
    if (ownerId) emitAiCanvasPreviewEvent({ phase: 'detach', jobId: ownerId, reason: 'session-ended' })
    pendingHandoffCanvasJobId = ''
    directCanvasOwnerId.value = ''
    uncertainCanvasCreation.value = null
    preparingCanvas.value = false
    livePreviewGeneration += 1
    livePreviewPendingFrame = null
    livePreviewOldestPendingAt = null
    clearTimeout(livePreviewFlushTimer)
    livePreviewFlushTimer = null
    livePreviewActive.value = false
    livePreviewJobId = ''
    livePreviewEditorStarted = false
    livePreviewRenderedDocument = null
    livePreviewBaselineDocument = null
    livePreviewDirectSettlePromise = null
    livePreviewDirectSettleJobId = ''
    directTerminalTargetJobId = ''
  }
  monitoringSuspendedJobId = ''
  directCanvasRecoveryJobId.value = ''
  const previousJobId = String(job.value?.id || '')
  if (!detach && previousJobId && !livePreviewActive.value && !isDirectExecutionJob()) {
    emitAiCanvasPreviewEvent({ phase: 'clear', jobId: previousJobId })
  }
  if (!detach && !isDirectExecutionJob()) void revertLiveDraftPreview()
  livePreviewSuppressedJobId = ''
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
  runningPrompt.value = ''
  followupPrompt.value = ''
  pendingFollowupPrompt.value = ''
  retryPrompt.value = ''
  sourceContext.value = null
  sourceFingerprint.value = ''
  submitAttempt = null
  saveCloudAttempt = null
  followupAttempt = null
  retryAttempt = null
  queueAttempt = null
  clearAgentRuntimeState()
  currentSessionTitle.value = '新对话'
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
  return true
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
    : eventType === 'tag_suggestions'
      ? sanitizeMindmapAiTagSuggestionsPayload(rawPayload)
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
  // Keep the canvas centered on the node changed by each AI draft update.
  // Edit.vue retries until a newly-created node has been rendered.
  const affectedUids = [
    ...(Array.isArray(payload?.directCommit?.affectedUids) ? payload.directCommit.affectedUids : []),
    ...(Array.isArray(payload?.affectedUids) ? payload.affectedUids : []),
  ]
    .map(uid => String(uid || '').trim())
    .filter(Boolean)
  // Live-preview frames focus after their renderer commit. Focusing here as
  // well would center the old layout first and the new layout a moment later,
  // which is perceived as a flash. Keep this event only as a fallback when
  // the current job has no canvas preview.
  if (affectedUids.length && !livePreviewEligible.value) {
    bus.emit('focusAiNode', {
      jobId: String(jobId),
      focusKey: `${String(jobId)}:${sequence}:${affectedUids.at(-1)}`,
      nodeUids: [...new Set(affectedUids)],
    })
  }
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

function livePreviewFrameDelay(frame = livePreviewPendingFrame) {
  return getMindmapAiPlaybackPacing({
    pendingCharacters: frame?.pendingCharacters,
    pendingNodes: frame?.pendingNodes,
    oldestPendingAt: livePreviewOldestPendingAt,
    terminal: isTerminalStatus(job.value?.status),
  }).delayMs
}

function scheduleLivePreviewFlush(delay = livePreviewFrameDelay()) {
  if (livePreviewFlushTimer || livePreviewFlushInFlight) return
  livePreviewFlushTimer = setTimeout(() => {
    livePreviewFlushTimer = null
    void flushLiveDraftPreview()
  }, delay)
}

function emitAiCanvasPreviewEvent(payload) {
  if (!payload?.jobId) return
  void emitEditorRequest('aiDraftPreview', payload).catch(() => {})
}

function toggleLivePreviewPlayback(paused = !livePreviewPaused.value) {
  if (!livePreviewPlaybackAvailable.value) return false
  const nextPaused = Boolean(paused)
  if (nextPaused && directTerminalTargetJobId === String(job.value?.id || '')) return false
  if (livePreviewPaused.value === nextPaused) return true
  livePreviewPaused.value = nextPaused
  clearTimeout(livePreviewFlushTimer)
  livePreviewFlushTimer = null
  if (!nextPaused) {
    // Resume from the newest queued snapshot. nextMindmapAiDraftFrame keeps
    // the already rendered tree as its baseline, so resuming never flashes
    // back to an older server frame.
    scheduleLivePreviewFlush(0)
  }
  return true
}

async function flushLiveDraftPreview() {
  if (livePreviewFlushInFlight) return
  if (livePreviewPaused.value) return
  const frame = livePreviewPendingFrame
  livePreviewPendingFrame = null
  if (!frame) {
    livePreviewOldestPendingAt = null
    return
  }
  const { generation, jobId, document, operationCursor } = frame
  livePreviewFlushInFlight = true
  let previewError = null
  let shouldRevert = false
  const request = (async () => {
    try {
      // A previous task's revert must finish before this task can capture a
      // new editor baseline. Recheck identity after the asynchronous barrier.
      if (!(await livePreviewRevertPromise)) {
        throw new Error('上一项 AI 实时预览尚未成功撤回')
      }
      if (
        generation !== livePreviewGeneration
        || job.value?.id !== jobId
        || !livePreviewActive.value
        || livePreviewJobId !== jobId
      ) return
      if (!livePreviewEditorStarted) {
        // Capture the editor's actual current tree before drawing anything.
        // The first draft may already contain a whole batch of new nodes.
        const started = await emitEditorRequest('aiDraftPreview', {
          phase: 'start', jobId, operationCursor,
          directCommitted: isDirectExecutionJob(),
        })
        if (generation === livePreviewGeneration && livePreviewActive.value && livePreviewJobId === jobId) {
          livePreviewEditorStarted = true
          livePreviewBaselineDocument = cloneRuntimeValue(started?.document)
          livePreviewRenderedDocument = cloneRuntimeValue(started?.document)
          // The frame currently being flushed is still waiting to render. It
          // is requeued below after the editor baseline has been captured.
          livePreviewFramesPending.value = true
          livePreviewRenderedNodeCount.value = countMindmapAiDraftNodes(started?.document?.root)
          const pending = livePreviewPendingFrame || frame
          livePreviewPendingFrame = {
            ...pending,
            pendingCharacters: getMindmapAiPendingCharacterCount(started?.document, pending.document),
          }
        }
        return
      }
      // Terminal events use the same node-by-node, character-by-character
      // planner as running updates; completion never skips queued characters.
      const nextFrame = nextMindmapAiDraftFrame(livePreviewRenderedDocument, document)
      const changeSummary = frame.changeSummary || summarizeMindmapAiDraftChanges(
        livePreviewBaselineDocument?.root,
        document?.root,
      )
      const frameChange = nextFrame.change || describeMindmapAiDraftChange(
        livePreviewRenderedDocument?.root,
        nextFrame.document?.root,
      )
      // Metadata belongs to the authoritative commit, not to the animation
      // timeline. A metadata-only target must not force an otherwise identical
      // root through the renderer or expose the full cloud tree early.
      const rootNoop = nextFrame.rootUnchanged === true
      if (!rootNoop) {
        livePreviewRendering.value = true
        try {
          await emitEditorRequest('aiDraftPreview', {
            phase: 'update',
            jobId,
            operationCursor,
            directCommitted: isDirectExecutionJob(),
            change: frameChange,
            changeSummary,
            previewNodeCount: Number.isSafeInteger(nextFrame.nodeCount)
              ? nextFrame.nodeCount
              : countMindmapAiDraftNodes(nextFrame.document?.root),
            previewTargetNodeCount: livePreviewTargetNodeCount.value,
            ...(nextFrame.typewriterTarget
              ? { typewriterTarget: nextFrame.typewriterTarget }
              : {}),
            ...(frameChange?.uid
              ? { focusKey: `${jobId}:${operationCursor}:${frameChange.uid}` }
              : {}),
            // The event bus is in-process. Edit.vue clones the root at the
            // renderer boundary, so cloning the complete frame here would
            // duplicate the largest cost in the live path.
            document: nextFrame.document,
          })
        } finally {
          livePreviewRendering.value = false
        }
      }
      if (generation === livePreviewGeneration && livePreviewActive.value && livePreviewJobId === jobId) {
        livePreviewEditorStarted = true
        if (!rootNoop) livePreviewRenderedDocument = nextFrame.document
        livePreviewFramesPending.value = nextFrame.remaining > 0 || Boolean(livePreviewPendingFrame)
        livePreviewRenderedNodeCount.value = Number.isSafeInteger(nextFrame.nodeCount)
          ? nextFrame.nodeCount
          : countMindmapAiDraftNodes(nextFrame.document?.root)
        livePreviewChangeSummary.value = changeSummary
        const renderedVersion = Number(operationCursor)
        if (frame.epoch === latestPreviewEpoch.value && Number.isSafeInteger(renderedVersion) && renderedVersion >= 0) {
          livePreviewRenderedVersion.value = Math.max(
            livePreviewRenderedVersion.value,
            renderedVersion,
          )
        }
        // Continue revealing this batch unless a newer server snapshot arrived.
        if (nextFrame.remaining > 0 && !livePreviewPendingFrame) {
          livePreviewPendingFrame = {
            ...frame,
            changeSummary,
            pendingCharacters: Math.max(0, (frame.pendingCharacters || 0) - 1),
            pendingNodes: nextFrame.remaining,
          }
        }
      }
    } catch (error) {
      previewError = formatMindmapAiError(error, 'AI 实时画布预览失败')
      shouldRevert = generation === livePreviewGeneration
        && livePreviewActive.value && livePreviewJobId === jobId
    }
  })()
  livePreviewFlushPromise = request
  await request
  livePreviewFlushInFlight = false

  if (previewError) {
    if (generation === livePreviewGeneration) livePreviewError.value = previewError
    if (shouldRevert && !isDirectExecutionJob()) {
      // Wait until the in-flight frame is fully out of the way before sending
      // the revert request; otherwise the revert can overtake the frame.
      void revertLiveDraftPreview().then((restored) => {
        if (restored && visible.value && job.value?.id === jobId) {
          livePreviewError.value = previewError
        }
      })
    }
  }
  const pending = livePreviewPendingFrame
  if (pending && pending.generation === livePreviewGeneration
    && livePreviewActive.value && livePreviewJobId === pending.jobId
    && !livePreviewPaused.value) {
    scheduleLivePreviewFlush()
  } else if (!pending && !livePreviewFlushInFlight) {
    livePreviewOldestPendingAt = null
  }
}

function queueLiveDraftPreview(document, operationCursor, targetNodeCount = null, { authoritativeTerminal = false } = {}) {
  const jobId = String(job.value?.id || '')
  if (!jobId) return
  if (directTerminalTargetJobId === jobId && !authoritativeTerminal) return
  if (livePreviewApplyingJobId === jobId) return
  if (livePreviewSuppressedJobId !== jobId && readLivePreviewSuppression(jobId)) {
    livePreviewSuppressedJobId = jobId
  }
  if (livePreviewSuppressedJobId === jobId) return
  if ((!livePreviewEligible.value && !authoritativeTerminal) || !document?.root || !job.value?.id) return
  const generation = livePreviewGeneration
  if (!livePreviewActive.value) {
    livePreviewActive.value = true
    livePreviewJobId = jobId
    livePreviewPaused.value = false
    livePreviewError.value = ''
    livePreviewRenderedVersion.value = -1
    livePreviewChangeSummary.value = null
  }
  const numericTargetNodeCount = Number(targetNodeCount)
  livePreviewTargetNodeCount.value = targetNodeCount !== null
    && targetNodeCount !== undefined
    && Number.isSafeInteger(numericTargetNodeCount)
    && numericTargetNodeCount >= 0
    ? numericTargetNodeCount
    : countMindmapAiDraftNodes(document.root)
  // Keep only the newest target while the editor renders. The flush reveals
  // large additive batches node by node without falling behind new snapshots.
  // The caller already owns an isolated draft snapshot; the in-process event
  // bus does not need a second full-tree clone here.
  if (livePreviewOldestPendingAt === null) livePreviewOldestPendingAt = Date.now()
  livePreviewPendingFrame = {
    generation,
    jobId,
    epoch: latestPreviewEpoch.value,
    operationCursor,
    document,
    // Estimate once per incoming target, not once per character. A replacement
    // target inherits queue age, so a fast producer cannot postpone catch-up.
    pendingCharacters: getMindmapAiPendingCharacterCount(livePreviewRenderedDocument, document),
  }
  livePreviewFramesPending.value = true
  // While playback is paused, keep only the newest server snapshot. Do not
  // schedule no-op flush timers for every incoming frame; resume explicitly
  // schedules one catch-up pass from that newest snapshot.
  if (!livePreviewPaused.value && !livePreviewFlushInFlight && !livePreviewFlushTimer) {
    scheduleLivePreviewFlush(livePreviewEditorStarted ? livePreviewFrameDelay() : 0)
  }
}

function revertLiveDraftPreview() {
  const jobId = livePreviewJobId || String(job.value?.id || '')
  if (jobId && isDirectExecutionJob()) {
    return isTerminalStatus(job.value?.status)
      ? settleDirectLiveDraftPreview(jobId)
      : Promise.resolve(false)
  }
  const shouldRevert = Boolean((livePreviewActive.value || livePreviewJobId) && jobId)
  livePreviewOldestPendingAt = null
  livePreviewGeneration += 1
  if (shouldRevert) {
    livePreviewReverting.value = true
    livePreviewRevertingJobId.value = jobId
  }
  livePreviewApplyingJobId = ''
  livePreviewPaused.value = false
  livePreviewActive.value = false
  livePreviewJobId = ''
  livePreviewError.value = ''
  livePreviewAutoAcceptFailedJobId.value = ''
  livePreviewPendingFrame = null
  livePreviewEditorStarted = false
  livePreviewBaselineDocument = null
  livePreviewRenderedDocument = null
  livePreviewRenderedVersion.value = -1
  livePreviewFramesPending.value = false
  livePreviewRendering.value = false
  livePreviewRenderedNodeCount.value = 0
  livePreviewTargetNodeCount.value = 0
  livePreviewChangeSummary.value = null
  clearTimeout(livePreviewFlushTimer)
  livePreviewFlushTimer = null
  clearTimeout(livePreviewAutoAcceptTimer)
  livePreviewAutoAcceptTimer = null
  if (!shouldRevert) return livePreviewRevertPromise
  const generation = livePreviewGeneration
  const previousRevert = livePreviewRevertPromise
  const revert = (async () => {
    try {
      const previousSucceeded = await previousRevert
      if (!previousSucceeded && livePreviewRevertFailedJobId !== jobId) return false
      await livePreviewFlushPromise
      await emitEditorRequest('aiDraftPreview', { phase: 'revert', jobId })
      livePreviewRevertFailedJobId = ''
      return true
    } catch (error) {
      livePreviewRevertFailedJobId = jobId
      if (generation === livePreviewGeneration) {
        livePreviewError.value = formatMindmapAiError(error, 'AI 实时画布撤回失败')
        if (visible.value && job.value?.id === jobId) {
          livePreviewActive.value = true
          livePreviewJobId = jobId
        }
      }
      return false
    } finally {
      if (generation === livePreviewGeneration) {
        livePreviewReverting.value = false
        livePreviewRevertingJobId.value = ''
      }
    }
  })()
  livePreviewRevertPromise = revert
  return revert
}

function scheduleDefaultLivePreviewAcceptance(jobId) {
  if (livePreviewAutoAcceptPromise || livePreviewAutoAcceptFailedJobId.value === String(jobId)) return
  clearTimeout(livePreviewAutoAcceptTimer)
  livePreviewAutoAcceptTimer = setTimeout(() => {
    livePreviewAutoAcceptTimer = null
    void acceptCompletedLivePreviewByDefault(jobId)
  }, LIVE_PREVIEW_FRAME_INTERVAL_MS)
}

async function acceptCompletedLivePreviewByDefault(jobId = job.value?.id, { retry = false } = {}) {
  const normalizedJobId = String(jobId || '')
  if (livePreviewAutoAcceptPromise) return livePreviewAutoAcceptPromise
  if (
    !normalizedJobId
    || (!retry && livePreviewAutoAcceptFailedJobId.value === normalizedJobId)
    || livePreviewSuppressedJobId === normalizedJobId
    || job.value?.id !== normalizedJobId
    || job.value?.status !== 'ready'
    || form.sourceMode !== 'current'
    || !canApplyCurrentProposal.value
    || (livePreviewActive.value && livePreviewJobId !== normalizedJobId)
    || !proposal.value
    || proposal.value.id !== job.value?.proposalId
  ) return false
  if (retry) {
    livePreviewAutoAcceptFailedJobId.value = ''
    livePreviewError.value = ''
  }
  const generation = livePreviewGeneration
  const acceptance = (async () => {
    while (
      livePreviewCatchingUp.value
      || livePreviewPreparing.value
      || livePreviewRendering.value
      || livePreviewFlushInFlight
      || livePreviewPendingFrame
      || livePreviewFlushTimer
      || actionBusy.value
    ) {
      if (livePreviewPaused.value && !actionBusy.value) toggleLivePreviewPlayback(false)
      if (livePreviewPendingFrame && !livePreviewPaused.value
        && !livePreviewFlushTimer && !livePreviewFlushInFlight) {
        scheduleLivePreviewFlush(0)
      }
      await new Promise(resolve => setTimeout(resolve, LIVE_PREVIEW_FRAME_INTERVAL_MS))
      if (
        generation !== livePreviewGeneration
        || !componentAlive
        || job.value?.id !== normalizedJobId
        || job.value?.status !== 'ready'
        || (livePreviewActive.value && livePreviewJobId !== normalizedJobId)
      ) return false
    }
    if (
      generation !== livePreviewGeneration
      || !componentAlive
      || job.value?.id !== normalizedJobId
      || job.value?.status !== 'ready'
      || !canApplyCurrentProposal.value
      || (livePreviewActive.value && livePreviewJobId !== normalizedJobId)
    ) return false
    livePreviewAutoAccepting.value = true
    return applyProposal({ automatic: true })
  })()
  livePreviewAutoAcceptPromise = acceptance
  try {
    let accepted = false
    try {
      accepted = await acceptance
    } catch (error) {
      if (livePreviewApplyingJobId === normalizedJobId) livePreviewApplyingJobId = ''
      livePreviewError.value = formatMindmapAiError(error, 'AI 结果自动保存失败')
    }
    if (!accepted && job.value?.status === 'ready'
      && (!livePreviewActive.value || livePreviewJobId === normalizedJobId)) {
      livePreviewAutoAcceptFailedJobId.value = normalizedJobId
      livePreviewError.value ||= livePreviewActive.value
        ? 'AI 结果仍保留在画布中，自动保存未完成。可重试保存或撤销 AI 结果。'
        : 'AI 结果自动保存未完成。可在面板重试保存。'
    }
    return accepted
  } finally {
    if (livePreviewAutoAcceptPromise === acceptance) livePreviewAutoAcceptPromise = null
    livePreviewAutoAccepting.value = false
  }
}

async function holdLiveDraftPreviewForApply(jobId) {
  if (!(await livePreviewRevertPromise)) {
    throw new Error('上一项 AI 实时预览尚未成功撤回')
  }
  if (!livePreviewActive.value || livePreviewJobId !== String(jobId)) return ''
  if (livePreviewCatchingUp.value || livePreviewPreparing.value) {
    throw new Error('AI 实时画布仍在补齐，请稍后再采纳')
  }
  // Stop later draft frames while keeping the already rendered canvas in
  // place. The editor uses its captured pre-preview baseline for validation.
  livePreviewApplyingJobId = String(jobId)
  livePreviewPendingFrame = null
  livePreviewOldestPendingAt = null
  clearTimeout(livePreviewFlushTimer)
  livePreviewFlushTimer = null
  await livePreviewFlushPromise
  if (!livePreviewActive.value || livePreviewJobId !== String(jobId)) {
    if (livePreviewApplyingJobId === String(jobId)) livePreviewApplyingJobId = ''
    throw new Error('AI 实时预览任务已经变化，请重新确认提案')
  }
  // Let an in-flight start request finish recording its editor baseline
  // before fencing all later frames. Otherwise the editor can be blocked
  // while this dialog incorrectly believes that no preview was started.
  livePreviewGeneration += 1
  livePreviewPendingFrame = null
  clearTimeout(livePreviewFlushTimer)
  livePreviewFlushTimer = null
  return livePreviewEditorStarted ? String(jobId) : ''
}

async function completeDirectCanvasHandoff(jobId) {
  try {
    await activateQueuedFollowupTurn(jobId)
    if (directCanvasOwnerId.value === jobId) directCanvasOwnerId.value = ''
    return true
  } catch (error) {
    if (componentAlive && directCanvasOwnerId.value === jobId) {
      livePreviewError.value = formatMindmapAiError(error, '下一轮 AI 任务尚未确认，已保持画布只读，请重试同步')
    }
    return false
  }
}

function settleDirectLiveDraftPreview(jobId = job.value?.id) {
  const normalizedJobId = String(jobId || '')
  if (!normalizedJobId || job.value?.id !== normalizedJobId
    || !isTerminalStatus(job.value?.status)) return Promise.resolve(false)
  if (livePreviewSuppressedJobId === normalizedJobId && !directCanvasOwned.value) return Promise.resolve(true)
  if (livePreviewSuppressedJobId === normalizedJobId && directCanvasOwnerId.value === normalizedJobId) {
    return completeDirectCanvasHandoff(normalizedJobId)
  }
  if (livePreviewDirectSettlePromise) {
    return livePreviewDirectSettleJobId === normalizedJobId
      ? livePreviewDirectSettlePromise : Promise.resolve(false)
  }
  if (directCanvasOwnerId.value && directCanvasOwnerId.value !== normalizedJobId) return Promise.resolve(false)
  const generation = livePreviewGeneration
  const isCurrent = () => componentAlive && job.value?.id === normalizedJobId
    && generation === livePreviewGeneration && directCanvasOwnerId.value === normalizedJobId
  const settlement = (async () => {
    try {
      directCanvasOwnerId.value = normalizedJobId
      await emitEditorRequest('aiDraftPreview', {
        phase: 'start', jobId: normalizedJobId, directCommitted: true,
      })
      await reconcileQueuedCanvasRequest(normalizedJobId)
      if (!isCurrent()) return false
      // The final HTTP checkpoint is another playback target, never a direct
      // canvas replacement. This also covers missed SSE frames and failures
      // after partially committed cloud edits.
      const terminal = await emitEditorRequest('aiDraftPreview', {
        phase: 'authoritative-target', jobId: normalizedJobId,
      })
      if (!isCurrent()) return false
      directTerminalTargetJobId = normalizedJobId
      queueLiveDraftPreview(terminal.document, latestPreviewVersion.value, null, { authoritativeTerminal: true })
      // Internal draining is not a user playback action. In particular a
      // cancel request intentionally disables the pause/resume controls.
      livePreviewPaused.value = false
      let lastProgressAt = Date.now()
      let lastRenderedDocument = livePreviewRenderedDocument
      while (livePreviewFlushInFlight || livePreviewPendingFrame || livePreviewFlushTimer) {
        if (livePreviewRenderedDocument !== lastRenderedDocument) {
          lastRenderedDocument = livePreviewRenderedDocument
          lastProgressAt = Date.now()
        }
        if (Date.now() - lastProgressAt > 15_000) {
          throw new Error('AI 结果显示暂时停滞，已保留当前画布，请重试同步')
        }
        if (livePreviewPendingFrame && !livePreviewFlushInFlight && !livePreviewFlushTimer) {
          scheduleLivePreviewFlush(0)
        }
        await new Promise(resolve => setTimeout(resolve, LIVE_PREVIEW_FRAME_INTERVAL_MS))
        if (!isCurrent()) return false
      }
      if (livePreviewError.value) throw new Error(livePreviewError.value)
      livePreviewApplyingJobId = normalizedJobId
      await emitEditorRequest('aiDraftPreview', {
        phase: 'direct-committed',
        jobId: normalizedJobId,
        targetToken: terminal.targetToken,
        nodeCount: livePreviewRenderedNodeCount.value,
        targetNodeCount: livePreviewTargetNodeCount.value,
        changeSummary: livePreviewChangeSummary.value,
        message: job.value?.status === 'completed_no_change'
          ? 'AI 已完成，当前脑图无需修改'
          : 'AI 已直接更新当前脑图',
      })
    } catch (error) {
      if (!isCurrent()) return false
      livePreviewApplyingJobId = ''
      livePreviewPendingFrame = null
      livePreviewOldestPendingAt = null
      clearTimeout(livePreviewFlushTimer)
      livePreviewFlushTimer = null
      livePreviewError.value = formatMindmapAiError(error, 'AI 直写结果校准失败')
      return false
    }
    if (!isCurrent()) return false
    finishLiveDraftPreviewAfterApply(normalizedJobId)
    directTerminalTargetJobId = ''
    return completeDirectCanvasHandoff(normalizedJobId)
  })()
  livePreviewDirectSettlePromise = settlement
  livePreviewDirectSettleJobId = normalizedJobId
  return settlement.finally(() => {
    if (livePreviewDirectSettlePromise === settlement) {
      livePreviewDirectSettlePromise = null
      livePreviewDirectSettleJobId = ''
    }
  })
}

function finishLiveDraftPreviewAfterApply(jobId) {
  if (livePreviewJobId !== String(jobId)) return
  if (directCanvasRecoveryJobId.value === String(jobId)) {
    directCanvasRecoveryJobId.value = ''
    restoreError.value = ''
  }
  livePreviewGeneration += 1
  livePreviewApplyingJobId = ''
  // The authoritative job status may arrive a moment after the editor ACK.
  // Fence late terminal hydration so it cannot reopen an accepted preview.
  livePreviewSuppressedJobId = String(jobId)
  persistLivePreviewSuppression(String(jobId))
  livePreviewPaused.value = false
  livePreviewActive.value = false
  livePreviewJobId = ''
  livePreviewError.value = ''
  livePreviewAutoAcceptFailedJobId.value = ''
  livePreviewPendingFrame = null
  livePreviewOldestPendingAt = null
  livePreviewEditorStarted = false
  livePreviewRenderedDocument = null
  livePreviewRenderedVersion.value = -1
  livePreviewFramesPending.value = false
  livePreviewRendering.value = false
  livePreviewRenderedNodeCount.value = 0
  livePreviewTargetNodeCount.value = 0
  livePreviewChangeSummary.value = null
  clearTimeout(livePreviewFlushTimer)
  livePreviewFlushTimer = null
}

function acceptDraftPreview(preview, { realtimeFrame = false } = {}) {
  // Direct jobs have already persisted this snapshot on the server. The same
  // checkpoint is still safe to render locally as a read-only progress frame;
  // final consistency remains guarded by the collaboration revision reload.
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
  const epoch = Number(preview?.previewEpoch || 1)
  if (
    !preview.document?.root
    || !Number.isInteger(version)
    || !Number.isInteger(epoch)
    || epoch < 1
    || compareMindmapAiPreviewCoordinates(
      { epoch, version },
      { epoch: latestPreviewEpoch.value, version: latestPreviewVersion.value },
    ) <= 0
  ) return false
  if (epoch > latestPreviewEpoch.value) {
    // A restarted generator owns a new monotonic timeline. Preserve the
    // currently displayed document as its visual baseline, but reset delivery
    // progress so a lower cursor in the new epoch cannot be mistaken for an
    // already-rendered old frame.
    livePreviewRenderedVersion.value = -1
  }
  latestPreviewEpoch.value = epoch
  latestPreviewVersion.value = version
  draftDocument.value = cloneRuntimeValue(preview.document)
  const targetNodeCount = countMindmapAiDraftNodes(draftDocument.value.root)
  queueLiveDraftPreview(draftDocument.value, version, targetNodeCount)
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
  if (messageModeActive.value || isDirectExecutionJob() || isTerminalStatus(job.value?.status)) return
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
  if (isTerminalStatus(job.value.status)) void finalizeTerminalJob(jobId)
  else if (['artifact_ready', 'artifact_needs_review', 'artifact_no_change'].includes(event?.eventType)
    || isTerminalStatus(payload.status)) schedulePoll(0, true)
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
  if (!['applied', 'undone', 'completed_direct'].includes(parentJob?.status)) return 'artifact'
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
    topic: { intent: 'create', prompt: '从这个主题开始搭建一张清晰的脑图，先列出核心概念和主要分支。' },
    outline: { intent: 'create', prompt: '先列出这个主题的主要分支，并说明每个分支应该继续展开什么。' },
    question: { intent: 'discuss', prompt: '和我一起讨论这张脑图适合如何组织，先指出最值得澄清的问题。' },
    analyze: { intent: 'discuss', prompt: '分析当前脑图的结构、重点和薄弱处，给出可以直接执行的改进建议。' },
    supplement: { intent: 'expand', prompt: '补充当前最薄弱的分支，优先添加缺失的关键概念、例子和下一步行动。' },
    gaps: { intent: 'discuss', prompt: '找出当前脑图的信息缺口、结构断点和容易被忽略的内容。' },
    duplicates: { intent: 'discuss', prompt: '检查当前脑图中的重复、冲突、含义相近节点和层级遗漏，并说明判断依据。' },
  }
  const starter = starters[type]
  if (!starter) return
  form.intent = starter.intent
  form.prompt = starter.prompt
  form.sourceMode = editorContext.value ? 'current' : 'new'
  discussionMode.value = starter.intent === 'discuss'
  onIntentChange(form.intent)
  void nextTick(() => composerInputRef.value?.focus?.())
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

async function queueRunningMessage() {
  const parentJob = job.value
  const prompt = runningPrompt.value.trim()
  if (!parentJob?.id || !prompt || continuing.value) return false
  const selectedAgent = agents.value.find(item => item.agentKey === form.agentKey)
  if (!selectedAgent || selectedAgent.status !== 'enabled') {
    ElMessage.warning('当前 Agent 暂时不可用，请稍后重试或切换 Agent')
    return false
  }
  const parentJobId = String(parentJob.id)
  const requestPayload = {
    prompt,
    route: runningMessageRoute.value === 'next' ? 'next' : 'current',
    agentKey: form.agentKey,
    modelId: form.agentKey === 'native_mindmap' ? form.modelId : undefined,
    intent: effectiveFormIntent.value,
  }
  const identity = beginActionIdentity('queue', { jobId: parentJobId })
  continuing.value = true
  let requestStarted = false
  let responseReceived = false
  let reusedPersistedAttempt = false
  try {
    // Do not overwrite the single durable queue slot while an earlier request
    // still has an unknown outcome. Recover it before accepting another one.
    await reconcileQueuedCanvasRequest(parentJobId)
    assertActionIdentity(identity)
    const persistedAttemptKey = readPersistedAttempts().queue?.key
    queueAttempt = await resolveDurableAttempt(
      'queue',
      queueAttempt,
      { parentJobId, requestPayload },
      {
        createKey: () => createMindmapAiIdempotencyKey('mindmap-ai-queue'),
        metadata: {
          parentJobId,
          parentTurnIndex: parentJob.turnIndex,
          sessionId: parentJob.sessionId,
          knownMaxTurnIndex: Math.max(
            Number(parentJob.turnIndex || 0),
            ...sessionTurns.value.map(turn => Number(turn?.job?.turnIndex || 0)),
          ),
          knownJobIds: Array.from(new Set([
            parentJobId,
            ...sessionTurns.value.map(turn => String(turn?.job?.id || '')),
          ].filter(Boolean))),
          requestPayload,
        },
      },
    )
    reusedPersistedAttempt = queueAttempt.key === persistedAttemptKey
    const durableAttempt = readPersistedAttempts().queue
    requestStarted = true
    const response = await continueMindmapAiJob(
      parentJobId,
      requestPayload,
      queueAttempt.key,
    )
    responseReceived = true
    assertActionIdentity(identity)
    const childJob = assertFollowupAttemptResult(
      response.data,
      durableAttempt,
      parentJob.sessionId,
    )
    upsertSessionTurn(childJob, prompt)
    appendClientPrompt(childJob.id, prompt, childJob.turnIndex)
    runningPrompt.value = ''
    clearDurableAttempt('queue', queueAttempt.key)
    queueAttempt = null
    restoreDurableAttemptNotice()
    ElMessage.success(
      runningMessageRoute.value === 'current'
        ? '已加入当前任务，将在下一个安全边界采用'
        : '已排入下一轮，上一轮结果确认保存后会自动继续',
    )
    return true
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return false
    if (!requestStarted) {
      ElMessage.error(formatMindmapAiError(error, '上一条排队请求尚未确认，请恢复连接后重试'))
      return false
    }
    if (!responseReceived && !reusedPersistedAttempt && isDefinitiveAiCreationRejection(error)) {
      clearDurableAttempt('queue', queueAttempt?.key)
      queueAttempt = null
      ElMessage.error(formatMindmapAiError(error, '排队请求被拒绝'))
      return false
    }
    try {
      const recoveredChild = await reconcileQueuedCanvasRequest(parentJobId)
      assertActionIdentity(identity)
      if (recoveredChild) {
        runningPrompt.value = ''
        ElMessage.success('已恢复上一条排队请求，当前生成完成后会自动继续')
        return true
      }
    } catch (recoveryError) {
      if (recoveryError?.code === 'AI_ACTION_SUPERSEDED') return false
    }
    if (isDirectExecutionJob(parentJob)) {
      livePreviewError.value = '下一轮请求结果尚未确认；本轮完成后将保持脑图只读，确认排队任务后继续'
    }
    ElMessage.error(formatMindmapAiError(
      error,
      runningMessageRoute.value === 'current' ? '加入当前任务失败' : '排队下一轮请求失败',
    ))
    return false
  } finally {
    continuing.value = false
  }
}

async function sendComposerMessage() {
  if (!composerCanSend.value) return
  if (running.value) await queueRunningMessage()
  else if (!job.value) await submitJob()
  else if (retryAvailable.value) await retryJob()
  else if (followupAvailable.value) await continueJob()
}

function onComposerKeydown(event) {
  if (event?.key === 'Escape' && running.value && !cancelling.value) {
    event.preventDefault()
    void confirmCancelFromKeyboard()
    return
  }
  if (
    event?.key !== 'Enter'
    || (!event.metaKey && !event.ctrlKey)
    || event.shiftKey
    || event.isComposing
    || event.keyCode === 229
  ) return
  event.preventDefault()
  void sendComposerMessage()
}

async function confirmCancelFromKeyboard() {
  if (cancelConfirming.value || cancelling.value || !job.value?.id) return false
  cancelConfirming.value = true
  try {
    await ElMessageBox.confirm(
      '停止后不会继续产生新的 AI 修改；已生成且可保存的画布结果会保留。',
      '停止 AI 任务？',
      {
        type: 'warning',
        confirmButtonText: '停止任务',
        cancelButtonText: '继续生成',
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
        closeOnPressEscape: true,
      },
    )
    return await cancelJob()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(formatMindmapAiError(error, '停止确认窗口打开失败'))
    }
    return false
  } finally {
    cancelConfirming.value = false
  }
}

async function requestEditorContext({ previewJobId = '' } = {}) {
  const context = await new Promise((resolve, reject) => {
    const handled = bus.emit('requestAiMindmapContext', { previewJobId, resolve, reject })
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
  return persistJobPointer(storedJob, job.value.status)
}

function persistJobPointer(pointer, status) {
  const terminal = isTerminalStatus(status)
  const storageKey = terminal ? RECENT_JOB_STORAGE_KEY : ACTIVE_JOB_STORAGE_KEY
  if (!writeMindmapAiOwnerSessionItem(storageKey, pointer.ownerUserId, JSON.stringify(pointer))) return false
  // A failed write must not erase the last usable recovery pointer.
  clearMindmapAiOwnerSessionItem(
    terminal ? ACTIVE_JOB_STORAGE_KEY : RECENT_JOB_STORAGE_KEY,
    pointer.ownerUserId,
  )
  return true
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
    // Timeline delivery can beat SSE. Its display-event deduplication must not
    // consume the only trigger for terminal hydration and canvas settlement.
    // Full restoration waits until source context has been restored below.
    if (!restoringJob.value && isTerminalStatus(job.value?.status)) {
      void finalizeTerminalJob(expectedJobId)
    }
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
  const turns = [...sessionTurns.value]
  const activeStatuses = new Set([
    'queued', 'preparing', 'running', 'validating', 'cancel_requested',
  ])
  const activeTurns = turns
    .filter(turn => activeStatuses.has(turn?.job?.status))
    .sort((left, right) => (
      Number(left?.job?.turnIndex || 0) - Number(right?.job?.turnIndex || 0)
    ))
  if (activeTurns.length) return activeTurns[0]
  const waitingTurns = turns
    .filter(turn => turn?.job?.status === 'waiting_turn')
    .sort((left, right) => (
      Number(left?.job?.turnIndex || 0) - Number(right?.job?.turnIndex || 0)
    ))
  if (waitingTurns.length) return waitingTurns[0]
  return turns
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再查看历史轮次')
    return false
  }
  if (livePreviewActive.value && !(await revertLiveDraftPreview())) return false
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
    latestPreviewEpoch.value = 1
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再重新加载当前轮次')
    return false
  }
  selectedTurnJobId.value = String(job.value.id)
  draftDocument.value = null
  latestPreviewVersion.value = -1
  latestPreviewEpoch.value = 1
  return refreshDraftPreview(job.value.id)
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
  await flushPendingCloudMutationIntents({ allowDuringLivePreview: true })
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
    || (
      candidateParentId !== parentJobId
      && !(
        ['current', 'next'].includes(attempt?.requestPayload?.route)
        && knownJobIds.has(candidateParentId)
      )
    )
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再恢复会话记录')
    return Promise.resolve(false)
  }
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
      generationMode: 'balanced',
      maxNodes: sessionJob.maxNodes,
      maxDepth: sessionJob.maxDepth,
      interactionMode: isMindmapAiMessageJob(sessionJob) ? 'discussion' : 'edit',
    },
    savedAt: Date.now(),
  }
}

async function switchToSession(session, { authoritativeJob = null } = {}) {
  if (!componentAlive || sessionSwitching.value || !currentAiOwnerUserId() || sessionUnavailableReason(session)) return false
  if (String(session.currentJob?.id) === String(job.value?.id)) {
    visible.value = true
    sessionMenuVisible.value = false
    return true
  }
  if (actionBusy.value || running.value) return false
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再切换会话')
    return false
  }
  const openingContext = taskOpenContextKey()
  let generation = restoreGeneration
  const isCurrent = () => componentAlive && generation === restoreGeneration
    && openingContext === taskOpenContextKey()
  sessionSwitching.value = true
  sessionMenuVisible.value = false
  try {
    const selectedJob = authoritativeJob || (await getMindmapAiJob(session.currentJob.id)).data
    if (!isCurrent()) return false
    if (!selectedJob?.id || !selectedJob.sessionId || String(selectedJob.id) !== String(session.currentJob.id)
      || selectedJob.sessionId !== session.sessionId
      || sessionUnavailableReason({ currentJob: selectedJob })) {
      throw new Error('所选任务与当前脑图或会话不匹配，已停止切换')
    }
    // Task-center entry may precede the first opening of the AI panel.
    if (!agents.value.length) await loadCapabilities({ recoveryGeneration: generation })
    if (!isCurrent() || running.value || livePreviewCanvasMutationBlocked.value) return false
    const pointer = sessionPointer({ ...session, currentJob: selectedJob })
    if (!persistJobPointer(pointer, selectedJob.status)) {
      throw new Error('浏览器无法保存所选会话的恢复指针。')
    }
    // The authoritative job has been accepted. No await separates this final
    // ownership check and reset; downstream resource failures can retry via
    // the newly persisted pointer without losing the previous one on failure.
    if (!resetNewJob({ clearStoredJob: false, preserveForm: true })) return false
    generation = restoreGeneration
    visible.value = true
    currentSessionTitle.value = session.title
    const restored = await restoreActiveJob({ generation, allowRecent: true })
    if (!isCurrent()) return false
    if (!restored && !restoreError.value) {
      restoreError.value = '所选会话暂时无法恢复，请重试。'
    }
    return restored
  } catch (error) {
    if (isCurrent() && !isAbortError(error)) {
      restoreError.value = formatMindmapAiError(error, '所选会话暂时无法恢复，请重试。')
    }
    return false
  } finally {
    // This flag is a mutex: no successor switch can start before it clears.
    sessionSwitching.value = false
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
    if (reconcilingCreateAttempt && createAttempt.requestPayload?.executionMode === 'direct') {
      // Restore the request fence before contacting a task that may still be
      // writing. A page reload must not turn an uncertain POST into an unlocked
      // editor or treat a racing GET 404 as proof of absence.
      const preparationId = await prepareDirectCanvasRequest(createAttempt.key)
      const identity = beginActionIdentity('recover-create', { jobId: null })
      uncertainCanvasCreation.value = {
        preparationId,
        recover: async () => {
          let recovered
          try { recovered = await reconcileMindmapAiJob(createAttempt.key) }
          catch (error) {
            if (!isHttpNotFound(error)) throw error
            recovered = await createMindmapAiJob(createAttempt.requestPayload, createAttempt.key)
          }
          assertActionIdentity(identity)
          restoreJobSourceState(recovered.data, saved)
          const activated = await activateCreatedJob(recovered.data, {
            identity,
            requestPayload: createAttempt.requestPayload,
            requestConfiguration: createAttempt.configuration,
            attemptKey: createAttempt.key,
            preparationId,
            recoverExisting: true,
          })
          void restoreSessionTimeline(recovered.data.sessionId, {
            expectedJobId: recovered.data.id, recoveryGeneration: generation,
          })
          return activated
        },
      }
      return await reconcilePendingCanvasCreation()
    }
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
    await reconcileRestoredSourceBaseline(job.value, saved)
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
      await finalizeTerminalJob(job.value.id, { recoveryGeneration: generation, refresh: false })
      if (
        !componentAlive
        || generation !== restoreGeneration
        || restoreController !== controller
        || !job.value?.id
      ) return false
    } else if (isDirectExecutionJob(job.value)) {
      return await resumeRestoredDirectJob(job.value.id, { generation, signal: controller.signal })
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
  if (uncertainCanvasCreation.value) return reconcilePendingCanvasCreation()
  if (directCanvasRecoveryJobId.value
    && directCanvasRecoveryJobId.value === String(job.value?.id || '')) return retryLivePreviewSync()
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再恢复任务')
    return false
  }
  invalidateRestoreOperations()
  return restoreActiveJob({ generation: restoreGeneration })
}

function discardStoredJobRecovery() {
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再放弃恢复任务')
    return false
  }
  if (!resetNewJob({ clearStoredJob: true, preserveForm: true })) return false
  applyDialogPreset(pendingDialogPreset)
  pendingDialogPreset = null
  reconcileAgentSelection()
}

function requestDialogClose() {
  visible.value = false
}

function onDialogClosed() {
  // Closing only hides the panel. The task and canvas remain mounted; only an
  // explicit undo/reject may restore the pre-AI document.
  sessionMenuVisible.value = false
  contextPickerVisible.value = false
}

async function finishCompletedAiGeneration() {
  // A running task is durable on the server and its latest preview is stored
  // in the draft checkpoint. Leaving the route must not cancel or block it;
  // the next editor instance restores the checkpoint and resumes SSE.
  if (form.sourceMode === 'current' && !messageModeActive.value && running.value
    && job.value?.status !== 'cancel_requested'
    && livePreviewSuppressedJobId !== String(job.value?.id || '')) return true
  if (livePreviewAutoAcceptPromise) return (await livePreviewAutoAcceptPromise) === true
  if (job.value?.status !== 'ready' || !job.value?.proposalId
    || livePreviewSuppressedJobId === String(job.value.id)) return true
  if (terminalHydrationState.value !== 'ready') {
    const hydrated = await hydrateTerminalResources(job.value.id)
    if (!hydrated) return false
  }
  return (await acceptCompletedLivePreviewByDefault(job.value.id)) === true
}

function startNewJob() {
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再新建对话')
    return false
  }
  if (!resetNewJob({ clearStoredJob: true, preserveForm: true })) return false
  form.prompt = ''
  discussionMode.value = false
  showAdvancedSettings.value = false
  applyDialogPreset(pendingDialogPreset)
  pendingDialogPreset = null
  reconcileAgentSelection()
  return true
}

function startRevisionFromRejected() {
  if (job.value?.status !== 'rejected' || actionBusy.value) return false
  const started = startNewJob()
  if (!started) return false
  if (editorContext.value?.document?.root) form.sourceMode = 'current'
  form.prompt = ''
  void nextTick(() => composerInputRef.value?.focus?.())
  ElMessage.info('已保留当前脑图，请输入修改要求后重新生成')
  return true
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
  // Hiding/reopening a panel is not a task transition. Preserve its playback,
  // baseline and cancellation/recovery controls even while it owns the canvas.
  if (job.value || preparingCanvas.value || directCanvasOwned.value || livePreviewActive.value) {
    visible.value = true
    return true
  }
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再打开新的 AI 任务')
    return false
  }
  const explicitPreset = normalizeDialogPreset(preset)
  if (explicitPreset) pendingDialogPreset = explicitPreset
  visible.value = true
  if (!resetNewJob({ clearStoredJob: false, preserveForm: true })) return false
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
  return restored
}

function isStoredJobForEditor(storedJob, context) {
  if (!storedJob || !context) return false
  if (storedJob.sourceType === 'cloud_document') {
    return Number.isSafeInteger(Number(context.mindmapId))
      && Number(context.mindmapId) === Number(storedJob.sourceMindmapId)
  }
  if (storedJob.sourceType === 'local_snapshot') {
    return Boolean(
      !context.mindmapId
      && context.documentId
      && storedJob.sourceDocumentId
      && String(context.documentId) === String(storedJob.sourceDocumentId),
    )
  }
  return false
}

function readAutoRecoveryPointer() {
  const activeJob = readUsableStoredJob(ACTIVE_JOB_STORAGE_KEY)
  if (activeJob) return activeJob
  const createAttempt = readPersistedAttempts().create
  if (!createAttempt?.key || !['cloud_document', 'local_snapshot'].includes(createAttempt.sourceType)) {
    return null
  }
  // The create request may still be in flight when the user leaves. The
  // normal restore path already knows how to reconcile this key; expose its
  // source identity here so we can decide whether this editor owns it.
  return {
    ...createAttempt,
    jobId: null,
    ownerUserId: currentAiOwnerUserId(),
  }
}

async function restoreActiveJobWhenEditorReady() {
  if (!componentAlive || visible.value || restoringJob.value || livePreviewCanvasMutationBlocked.value) return false
  if (getRequestedAiJobId()) return restoreRequestedAiJob()
  const storedJob = readAutoRecoveryPointer()
  if (!storedJob || !['cloud_document', 'local_snapshot'].includes(storedJob.sourceType)) return false
  try {
    const context = await requestEditorContext()
    if (!isStoredJobForEditor(storedJob, context)) return false
    return await showDialog()
  } catch (error) {
    // The editor may announce ready before its context can be read during a
    // route transition. Keep the durable pointer; the next explicit AI open
    // or editor-ready event can retry recovery without creating a task.
    if (!isAbortError(error)) restoreError.value = ''
    return false
  }
}

function getRequestedAiJobId(explicitJobId = '') {
  const candidate = explicitJobId || route.query?.aiJobId
  if (Array.isArray(candidate)) return String(candidate[0] || '').trim()
  return String(candidate || '').trim()
}

function taskOpenContextKey() {
  return JSON.stringify([currentAiOwnerUserId(), route.path, route.query])
}

async function restoreRequestedAiJob(explicitJobId = '') {
  const requestedJobId = getRequestedAiJobId(explicitJobId)
  if (!requestedJobId || !componentAlive || !currentAiOwnerUserId() || restoringJob.value || sessionSwitching.value) return false
  if (String(job.value?.id) === requestedJobId) {
    requestedTaskSequence += 1
    return switchToSession({ sessionId: job.value.sessionId, currentJob: job.value })
  }
  if (actionBusy.value || running.value || livePreviewCanvasMutationBlocked.value) return false
  const sequence = ++requestedTaskSequence
  const openingContext = taskOpenContextKey()
  const generation = restoreGeneration
  const isCurrent = () => componentAlive && sequence === requestedTaskSequence
    && openingContext === taskOpenContextKey()
  try {
    const context = await requestEditorContext()
    if (!isCurrent() || generation !== restoreGeneration) return false
    const response = await getMindmapAiJob(requestedJobId)
    if (!isCurrent() || generation !== restoreGeneration) return false
    const requestedJob = response?.data
    if (
      String(requestedJob?.id || '') !== requestedJobId
      || requestedJob.sourceType !== 'cloud_document'
      || Number(context?.mindmapId) !== Number(requestedJob.sourceMindmapId)
    ) {
      restoreError.value = '这个 AI 任务不属于当前脑图，已停止自动打开。'
      return false
    }
    const restored = await switchToSession({
      sessionId: requestedJob.sessionId,
      title: requestedJob.title || 'AI 对话',
      currentJob: requestedJob,
    }, { authoritativeJob: requestedJob })
    if (!isCurrent()) return false
    if (restored && getRequestedAiJobId() === requestedJobId) {
      const query = { ...route.query }
      delete query.aiJobId
      await router.replace({ path: route.path, query })
    }
    return restored
  } catch (error) {
    if (isCurrent() && generation === restoreGeneration && !isAbortError(error)) {
      restoreError.value = formatMindmapAiError(error, 'AI 任务暂时无法恢复')
    }
    return false
  }
}

async function onDeepLinkedAiTask(event) {
  await restoreRequestedAiJob(event?.detail?.jobId || '')
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
  if (!componentAlive || !job.value?.id || job.value.id === monitoringSuspendedJobId) return
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

async function reconcileQueuedCanvasRequest(parentJobId) {
  const parent = job.value
  if (!componentAlive || String(parent?.id || '') !== String(parentJobId)) {
    const error = new Error('排队任务上下文已变化')
    error.code = 'AI_ACTION_SUPERSEDED'
    throw error
  }
  const attempt = readPersistedAttempts().queue
  if (!attempt?.key || String(attempt.sessionId || '') !== String(parent.sessionId || '')) return null
  const child = await replayFollowupAttempt(attempt, parent.sessionId)
  if (!componentAlive || String(job.value?.id || '') !== String(parentJobId)) {
    const error = new Error('排队任务上下文已变化')
    error.code = 'AI_ACTION_SUPERSEDED'
    throw error
  }
  if (!child?.id) throw new Error('下一轮请求尚未确认，请重试同步，脑图保持只读')
  const prompt = attempt.requestPayload?.prompt || ''
  upsertSessionTurn(child, prompt)
  appendClientPrompt(child.id, prompt, child.turnIndex)
  clearDurableAttempt('queue', attempt.key)
  if (queueAttempt?.key === attempt.key) queueAttempt = null
  restoreDurableAttemptNotice()
  // A previous failed queue recovery must not poison a later successful
  // terminal drain. Renderer failures are still recorded by the frame loop.
  if (livePreviewError.value === '下一轮请求结果尚未确认；本轮完成后将保持脑图只读，确认排队任务后继续') {
    livePreviewError.value = ''
  }
  return child
}

async function activateQueuedFollowupTurn(parentJobId) {
  if (!componentAlive || String(job.value?.id || '') !== String(parentJobId)) return false
  // Include a very fast child's terminal state: it still needs to acquire the
  // canvas and reconcile its final tree before manual editing may resume.
  const turn = [...sessionTurns.value].sort((a, b) => Number(a.job?.turnIndex || 0) - Number(b.job?.turnIndex || 0)).find(item => (
    String(item?.job?.parentJobId || '') === String(parentJobId)
    && String(item?.job?.id || '') !== String(parentJobId)
  ))
  if (!turn?.job?.id) return false
  let childJob = turn.job
  let initialPreview = null
  if (isDirectExecutionJob(childJob)) {
    // The previous settlement has committed but has not released its lock.
    // Start the child's session synchronously before any async activation work
    // can let collaboration paint its full cloud document outside playback.
    pendingHandoffCanvasJobId = String(childJob.id)
    await emitEditorRequest('aiDraftPreview', {
      phase: 'start', jobId: String(childJob.id), directCommitted: true,
    })
    if (!componentAlive || String(job.value?.id || '') !== String(parentJobId)) return false
    // Stored queue snapshots usually still say waiting_turn. Re-read the job
    // under its canvas fence before deciding whether it needs a cursor floor.
    const refreshed = await getMindmapAiJob(childJob.id)
    if (!componentAlive || String(job.value?.id || '') !== String(parentJobId)) return false
    if (String(refreshed.data?.id || '') !== String(childJob.id)) throw new Error('下一轮任务身份尚未确认')
    childJob = refreshed.data
    if (!isTerminalStatus(childJob.status) && childJob.status !== 'waiting_turn') {
      const latest = await getMindmapAiJobDraft(childJob.id)
      if (!componentAlive || String(job.value?.id || '') !== String(parentJobId)) return false
      const preview = latest.data
      const validPreview = preview?.available === true && preview.document?.root
        && Number.isSafeInteger(Number(preview.operationCursor))
        && Number(preview.operationCursor) >= 0
        && Number.isSafeInteger(Number(preview.previewEpoch || 1))
        && Number(preview.previewEpoch || 1) >= 1
      if (validPreview) initialPreview = preview
      else {
        // Completion can erase the checkpoint between the job and draft GETs.
        // Conversely a queued/preparing child legitimately has no first draft.
        const confirmed = await getMindmapAiJob(childJob.id)
        if (!componentAlive || String(job.value?.id || '') !== String(parentJobId)) return false
        if (String(confirmed.data?.id || '') !== String(childJob.id)) throw new Error('下一轮任务身份尚未确认')
        childJob = confirmed.data
        if (!isTerminalStatus(childJob.status)
          && !['waiting_turn', 'queued', 'preparing'].includes(childJob.status)) {
          throw new Error('下一轮最新草稿尚未同步，已保持画布只读，请重试同步')
        }
      }
    }
  }
  const identity = beginActionIdentity('queue-activate', { jobId: parentJobId })
  const prompt = turn.userMessage?.content || ''
  if (isDirectExecutionJob(childJob)) directCanvasOwnerId.value = String(childJob.id)
  const activated = await activateFollowupJob(childJob, {
    identity,
    requestPayload: {
      prompt,
      agentKey: childJob.agentKey || form.agentKey,
      modelId: childJob.agentKey === 'native_mindmap' ? form.modelId : undefined,
    },
    attemptKey: queueAttempt?.key || '',
    initialPreview,
  })
  if (activated && pendingHandoffCanvasJobId === String(childJob.id)) {
    directCanvasOwnerId.value = String(childJob.id)
    pendingHandoffCanvasJobId = ''
  }
  return activated
}

async function refreshDraftPreview(jobId) {
  if (!componentAlive || !jobId || job.value?.id !== jobId || jobId === monitoringSuspendedJobId) return false
  if (isMindmapAiMessageJob(job.value)) return false
  if (selectedTurnJobId.value && selectedTurnJobId.value !== String(jobId)) return false
  draftController?.abort()
  const controller = new AbortController()
  draftController = controller
  try {
    const response = await getMindmapAiJobDraft(jobId, { signal: controller.signal })
    if (!componentAlive || job.value?.id !== jobId || jobId === monitoringSuspendedJobId) return false
    return acceptDraftPreview(response.data)
  } catch (error) {
    if (!isAbortError(error) && job.value?.id === jobId && jobId !== monitoringSuspendedJobId) {
      realtimeError.value = formatMindmapAiError(error, '实时脑图草稿暂时不可用')
    }
    return false
  } finally {
    if (draftController === controller) draftController = null
  }
}

async function resumeRestoredDirectJob(jobId, { generation = restoreGeneration, signal } = {}) {
  const normalizedJobId = String(jobId || '')
  const playbackGeneration = livePreviewGeneration
  const isCurrent = () => componentAlive && generation === restoreGeneration
    && playbackGeneration === livePreviewGeneration
    && job.value?.id === normalizedJobId && !signal?.aborted
  if (!normalizedJobId || !isCurrent() || !isDirectExecutionJob()) return false
  if (directCanvasOwnerId.value && directCanvasOwnerId.value !== normalizedJobId) {
    throw new Error('上一轮 AI 画布尚未完成同步')
  }
  directCanvasRecoveryJobId.value = normalizedJobId
  directCanvasOwnerId.value = normalizedJobId
  stopPolling()
  stopRealtime('connecting')
  try {
    // Fence collaboration BEFORE reading the checkpoint. Reversing these two
    // awaits lets a newer HTTP/cloud tree become the baseline while an older
    // draft response is in flight, causing deletions and a visible rewind.
    await emitEditorRequest('aiDraftPreview', {
      phase: 'start', jobId: normalizedJobId, directCommitted: true,
    })
    if (!isCurrent()) return false
    const response = await getMindmapAiJobDraft(normalizedJobId, { signal })
    if (!isCurrent()) return false
    const preview = response.data
    const validPreview = preview?.available === true && preview.document?.root
      && Number.isSafeInteger(Number(preview.operationCursor))
      && Number(preview.operationCursor) >= 0
      && Number.isSafeInteger(Number(preview.previewEpoch || 1))
      && Number(preview.previewEpoch || 1) >= 1
    if (validPreview) {
      if (!acceptDraftPreview(preview)) {
        // A retry may observe exactly the checkpoint already accepted before
        // a renderer failure. Never reset the coordinates backwards to force
        // acceptance of an older response.
        if (!draftDocument.value?.root || compareMindmapAiPreviewCoordinates(
          { epoch: preview.previewEpoch || 1, version: preview.operationCursor },
          { epoch: latestPreviewEpoch.value, version: latestPreviewVersion.value },
        ) !== 0) throw new Error('最新草稿无法建立恢复起点，请重试同步')
        queueLiveDraftPreview(draftDocument.value, latestPreviewVersion.value)
      }
    } else {
      // The worker may complete and retire its checkpoint during the GET.
      // A task still preparing its first draft also has nothing to replay.
      const confirmed = await getMindmapAiJob(normalizedJobId, { signal })
      if (!isCurrent()) return false
      if (String(confirmed.data?.id || '') !== normalizedJobId) throw new Error('恢复任务身份尚未确认')
      job.value = mergeMindmapAiJobSnapshot(job.value, confirmed.data)
      if (!isTerminalStatus(job.value.status)
        && !['waiting_turn', 'queued', 'preparing'].includes(job.value.status)) {
        throw new Error('最新草稿尚未同步，脑图保持只读，请重试恢复任务')
      }
    }
    restoreError.value = ''
    livePreviewError.value = ''
    persistActiveJob()
    if (isTerminalStatus(job.value.status)) schedulePoll(0, true)
    else beginJobMonitoring({ resetCursor: false })
    directCanvasRecoveryJobId.value = ''
    return true
  } catch (error) {
    if (!isCurrent()) return false
    livePreviewError.value = formatMindmapAiError(error, '最新草稿恢复失败，脑图保持只读，请重试恢复任务')
    restoreError.value = livePreviewError.value
    throw error
  }
}

async function retryLivePreviewSync() {
  const jobId = String(job.value?.id || '')
  if (jobId && directCanvasOwned.value && isTerminalStatus(job.value?.status)) {
    if (livePreviewRecovering.value) return false
    livePreviewRecovering.value = true
    livePreviewError.value = ''
    try { return await finalizeTerminalJob(jobId, { retry: true }) }
    finally { livePreviewRecovering.value = false }
  }
  if (!jobId || livePreviewRecovering.value || isTerminalStatus(job.value?.status)) return false
  livePreviewRecovering.value = true
  const recoveryGeneration = restoreGeneration
  const retryingRender = Boolean(livePreviewError.value)
  livePreviewError.value = ''
  realtimeError.value = ''
  try {
    if (directCanvasRecoveryJobId.value === jobId) {
      return await resumeRestoredDirectJob(jobId, { generation: recoveryGeneration })
    }
    const refreshed = await refreshDraftPreview(jobId)
    if (
      !componentAlive
      || recoveryGeneration !== restoreGeneration
      || job.value?.id !== jobId
    ) return false
    if (!refreshed) {
      // An unchanged cursor is a valid retry after a rendering failure; do not
      // require the server to produce another edit before playback resumes.
      if (retryingRender && !realtimeError.value && draftDocument.value?.root) {
        queueLiveDraftPreview(draftDocument.value, latestPreviewVersion.value)
      } else throw new Error('实时草稿仍不可用，请稍后重试')
    }
    draftFreshness.value = 'fresh'
    draftFreshnessMessage.value = ''
    // Refreshing the exact draft repairs the visible canvas first; reconnect
    // the event stream afterwards so later frames continue without starting a
    // second AI task or losing the current event cursor.
    connectRealtime(jobId)
    schedulePoll(0)
    return true
  } catch (error) {
    if (
      componentAlive
      && recoveryGeneration === restoreGeneration
      && job.value?.id === jobId
    ) {
      draftFreshness.value = draftDocument.value?.root ? 'stale' : 'unavailable'
      draftFreshnessMessage.value = formatMindmapAiError(
        error,
        '实时草稿仍未恢复；当前画布已保留，系统会继续自动重试。',
      )
    }
    return false
  } finally {
    livePreviewRecovering.value = false
  }
}

async function restoreTerminalPreview(jobId, {
  recoveryGeneration = restoreGeneration,
} = {}) {
  if (isMindmapAiMessageJob(job.value) || isDirectExecutionJob(job.value)) return false
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
    if (
      displayCurrentJob
      && !['cancelled', 'failed', 'expired', 'stale', 'rejected'].includes(job.value.status)
    ) {
      draftDocument.value = cloneRuntimeValue(document)
      queueLiveDraftPreview(draftDocument.value, latestPreviewVersion.value + 1)
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
  const hydrationGeneration = ++terminalHydrationGeneration
  const isCurrent = () => componentAlive && recoveryGeneration === restoreGeneration
    && hydrationGeneration === terminalHydrationGeneration && job.value?.id === jobId
  terminalHydrationState.value = 'loading'
  terminalHydrationError.value = ''
  const messageJob = isMindmapAiMessageJob(job.value)
  const artifactReady = messageJob || !job.value.artifactId
    || await restoreTerminalPreview(jobId, { recoveryGeneration })
  if (!isCurrent()) return false
  // A direct proposal is a live undo receipt, not an immutable preview. Its
  // first GET can contain only the first batch (e.g. 8 of a final 84 nodes),
  // although its ID never changes. Refetch at every terminal hydration,
  // including failed/cancelled tasks whose earlier batches were committed.
  // Normal immutable proposals keep their existing same-ID cache behavior.
  const proposalReady = messageJob || !job.value.proposalId
    || (!isDirectExecutionJob() && proposal.value?.id === job.value.proposalId)
    || await loadProposal()
  if (!isCurrent()) return false
  let needsInputReady = job.value.status !== 'needs_input' || needsInputQuestions.value.length > 0
  if (!needsInputReady && job.value.sessionId) {
    await restoreSessionTimeline(job.value.sessionId, {
      expectedJobId: jobId,
      recoveryGeneration,
    })
    if (!isCurrent()) return false
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
    if (!isCurrent()) return false
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
    if (job.value.status === 'ready' && form.sourceMode === 'current'
      && canApplyCurrentProposal.value) {
      // The live canvas is the user's accepted result by default. Wait until
      // the final queued frame has painted, then persist the same result using
      // the normal apply path so its full AI undo snapshot is retained.
      scheduleDefaultLivePreviewAcceptance(jobId)
    }
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

function terminalJobResourceKey(candidate = job.value) {
  return JSON.stringify([candidate?.status, candidate?.artifactId || '', candidate?.proposalId || ''])
}

function finalizeTerminalJob(jobId = job.value?.id, {
  retry = false,
  refresh = true,
  recoveryGeneration = restoreGeneration,
} = {}) {
  if (!componentAlive || !jobId || job.value?.id !== jobId
    || recoveryGeneration !== restoreGeneration || !isTerminalStatus(job.value.status)) return Promise.resolve(false)
  let state = terminalFinalizationState
  if (!state || state.jobId !== jobId || state.generation !== recoveryGeneration) {
    state?.controller?.abort()
    state = { jobId, generation: recoveryGeneration, promise: null, completedKey: '', failedKey: '', controller: null }
    terminalFinalizationState = state
  }
  // Poll, timeline, repeated SSE and EOF all join the same work. In particular,
  // a forced poll must not abort or supersede a proposal GET already in flight.
  if (state.promise) return state.promise
  let resourceKey = terminalJobResourceKey()
  if (state.completedKey === resourceKey) return Promise.resolve(true)
  if (!retry && state.failedKey === resourceKey) return Promise.resolve(false)
  state.failedKey = ''
  const controller = new AbortController()
  state.controller = controller
  const isCurrent = () => componentAlive && terminalFinalizationState === state
    && recoveryGeneration === restoreGeneration && job.value?.id === jobId
  const work = (async () => {
    try {
      stopRealtime('completed')
      stopPolling()
      if (refresh) {
        const response = await getMindmapAiJob(jobId, { signal: controller.signal })
        if (!isCurrent()) return false
        job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
        persistActiveJob()
      }
      if (!isCurrent() || !isTerminalStatus(job.value.status)) return false
      resourceKey = terminalJobResourceKey()
      const direct = isDirectExecutionJob()
      if (!direct && ['failed', 'cancelled', 'expired', 'stale', 'rejected'].includes(job.value.status)
        && livePreviewActive.value) {
        if (!(await revertLiveDraftPreview())) throw new Error(livePreviewError.value || 'AI 实时预览撤回失败，请重试同步')
        if (!isCurrent()) return false
      }
      if (!direct && !livePreviewActive.value) emitAiCanvasPreviewEvent({ phase: 'clear', jobId })
      const resourcesReady = await hydrateTerminalResources(jobId, { recoveryGeneration })
      if (!isCurrent() || resourceKey !== terminalJobResourceKey()) return false
      let canvasReady = true
      if (direct) canvasReady = await settleDirectLiveDraftPreview(jobId)
      else if (!livePreviewActive.value) await activateQueuedFollowupTurn(jobId)
      // Settlement can transfer ownership to a queued child. Do not stop its
      // stream, overwrite its resource state, or release its canvas afterward.
      if (!isCurrent()) return canvasReady && resourcesReady
      if (resourceKey !== terminalJobResourceKey()) return false
      if (resourcesReady && canvasReady) state.completedKey = resourceKey
      else state.failedKey = resourceKey
      return resourcesReady && canvasReady
    } catch (error) {
      if (!isCurrent() || isAbortError(error)) return false
      state.failedKey = resourceKey
      terminalHydrationState.value = 'error'
      terminalHydrationError.value = formatMindmapAiError(error, '任务已完成，但结果状态暂时无法同步')
      scheduleTerminalHydrationRetry(jobId)
      return false
    }
  })()
  state.promise = work.finally(() => {
    state.promise = null
    if (state.controller === controller) state.controller = null
    // Apply/undo can advance a terminal status while resources are loading.
    // Finish that new state serially instead of publishing the old completion.
    if (isCurrent() && resourceKey !== terminalJobResourceKey() && isTerminalStatus(job.value.status)) {
      void finalizeTerminalJob(jobId)
    }
  })
  return state.promise
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
  if (!componentAlive || !jobId || job.value?.id !== jobId || jobId === monitoringSuspendedJobId) return
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    realtimeConnectionState.value = 'offline'
    return
  }
  if (isTerminalStatus(job.value.status)) return finalizeTerminalJob(jobId, { retry: force })
  pollController?.abort()
  const controller = new AbortController()
  pollController = controller
  try {
    const response = await getMindmapAiJob(jobId, { signal: controller.signal })
    if (!componentAlive || job.value?.id !== jobId || jobId === monitoringSuspendedJobId) return
    job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
    // 权威轮询成功说明任务连接已经恢复。先清除旧 SSE 警告；若随后草稿
    // 拉取仍失败，refreshDraftPreview 会写入更准确的草稿错误。
    realtimeError.value = ''
    persistActiveJob()
    if (isTerminalStatus(job.value.status)) {
      return await finalizeTerminalJob(jobId, { retry: force, refresh: false })
    } else if (!isMindmapAiMessageJob(job.value)) {
      await refreshDraftPreview(jobId)
    }
    if (!componentAlive || job.value?.id !== jobId || jobId === monitoringSuspendedJobId) return
    if (
      !isMindmapAiMessageJob(job.value)
      && !isTerminalStatus(job.value.status)
      && job.value.proposalId
      && proposal.value?.id !== job.value.proposalId
    ) {
      await loadProposal()
    }
    if (isTerminalStatus(job.value.status)) return await finalizeTerminalJob(jobId)
    const delay = realtimeConnectionState.value === 'connected' ? 6000 : 1500
    schedulePoll(delay)
  } catch (error) {
    if (!isAbortError(error) && job.value?.id === jobId && jobId !== monitoringSuspendedJobId) {
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
    previewEpoch: latestPreviewEpoch.value,
    signal: controller.signal,
    fetchDraft: getMindmapAiJobDraft,
    fetchDraftEnabled: true,
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
      appendAgentEvent(jobId, event)
      applyRealtimeJobEvent(jobId, event)
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
  }).then(async cursor => {
    if (generation !== realtimeGeneration || job.value?.id !== jobId) return
    realtimeController = null
    latestEventSequence.value = Math.max(
      latestEventSequence.value,
      Number(cursor?.afterSequence) || 0,
    )
    jobEventSequences.set(jobId, latestEventSequence.value)
    if (compareMindmapAiPreviewCoordinates(
      { epoch: cursor?.previewEpoch, version: cursor?.previewVersion },
      { epoch: latestPreviewEpoch.value, version: latestPreviewVersion.value },
    ) > 0) {
      latestPreviewEpoch.value = cursor.previewEpoch
      latestPreviewVersion.value = cursor.previewVersion
    }
    if (isTerminalStatus(job.value.status)) {
      realtimeConnectionState.value = 'completed'
      realtimeError.value = ''
      await finalizeTerminalJob(jobId)
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
    latestPreviewEpoch.value = 1
  } else {
    syncCurrentJobCursor(jobId)
  }
  if (hasUnresolvedGenerationRestart(jobId)) markGenerationRestarted()
  if (livePreviewPreparing.value && isDirectExecutionJob()) {
    directCanvasOwnerId.value = String(jobId)
    emitAiCanvasPreviewEvent({
      phase: 'start',
      jobId,
      directCommitted: true,
    })
  }
  if (!isMindmapAiMessageJob(job.value)) {
    void refreshDraftPreview(jobId)
  }
  schedulePoll(0)
  connectRealtime(jobId)
}

async function prepareDirectCanvasRequest(attemptKey, { drainLocalChanges = false } = {}) {
  const preparationId = `preparing:${attemptKey}`
  if (directCanvasOwnerId.value && directCanvasOwnerId.value !== preparationId) {
    throw new Error('上一轮 AI 画布尚未完成同步')
  }
  preparingCanvas.value = true
  directCanvasOwnerId.value = preparationId
  try {
    await emitEditorRequest('aiDraftPreview', {
      phase: 'prepare', jobId: preparationId, directCommitted: true,
      drainLocalChanges,
    })
  } catch (error) {
    await releaseCanvasPreparation(preparationId)
    throw error
  }
  return preparationId
}

async function adoptDirectCanvasRequest(nextJob, preparationId) {
  if (!preparationId) return
  if (!isDirectExecutionJob(nextJob)) {
    if (uncertainCanvasCreation.value?.preparationId === preparationId) uncertainCanvasCreation.value = null
    await releaseCanvasPreparation(preparationId)
    return
  }
  await emitEditorRequest('aiDraftPreview', {
    phase: 'start', jobId: nextJob.id, preparationId, directCommitted: true,
  })
  directCanvasOwnerId.value = String(nextJob.id)
  preparingCanvas.value = false
}

async function releaseCanvasPreparation(preparationId) {
  if (uncertainCanvasCreation.value?.preparationId === preparationId) return false
  if (preparationId && directCanvasOwnerId.value === preparationId) {
    try {
      await emitEditorRequest('aiDraftPreview', {
        phase: 'preparation-aborted', jobId: preparationId, notCreated: true,
      })
    } catch (error) {
      livePreviewError.value = formatMindmapAiError(error, '云端脑图同步失败')
      uncertainCanvasCreation.value = { preparationId, recover: async () => null }
      return false
    }
    if (directCanvasOwnerId.value === preparationId) directCanvasOwnerId.value = ''
  }
  if (!uncertainCanvasCreation.value) preparingCanvas.value = false
  emitAiEditingState()
  return true
}

// An HTTP error is not evidence that a durable job was not created. Retain the
// exact request identity and canvas ownership until reconciliation proves its
// result. The same recovery gate is used by create, follow-up and retry.
async function reconcilePendingCanvasCreation() {
  const pending = uncertainCanvasCreation.value
  if (!pending || livePreviewRecovering.value) return false
  livePreviewRecovering.value = true
  try {
    const recovered = await pending.recover()
    if (!componentAlive || uncertainCanvasCreation.value !== pending) return false
    // Only an explicit null means the request never created a job. A stale
    // activation returning false must keep recovery ownership, not unlock it.
    if (recovered !== true && recovered !== null) throw new Error('AI 请求结果仍未确认，请重试同步')
    uncertainCanvasCreation.value = null
    if (recovered === null && !(await releaseCanvasPreparation(pending.preparationId))) return false
    preparingCanvas.value = false
    livePreviewError.value = ''
    return true
  } catch (error) {
    if (componentAlive && uncertainCanvasCreation.value === pending) {
      livePreviewError.value = formatMindmapAiError(error,
        '请求结果尚未确认，已保持脑图只读；请恢复连接后重试确认，不要重复创建任务')
    }
    return false
  } finally {
    livePreviewRecovering.value = false
  }
}

async function activateCreatedJob(nextJob, { identity, requestPayload, requestConfiguration, attemptKey, preparationId, recoverExisting = false }) {
  assertActionIdentity(identity)
  await adoptDirectCanvasRequest(nextJob, preparationId)
  assertActionIdentity(identity)
  submitAttempt = null
  stopPolling()
  stopRealtime('idle')
  clearAgentRuntimeState()
  job.value = mergeMindmapAiJobSnapshot(job.value, nextJob)
  identity.jobId = job.value.id
  discussionMode.value = isMindmapAiMessageJob(job.value)
  currentSessionTitle.value = deriveMindmapAiSessionTitle(requestPayload.prompt, '新对话')
  jobConfiguration.value = requestConfiguration
  appendClientPrompt(job.value.id, requestPayload.prompt, job.value.turnIndex)
  upsertSessionTurn(job.value, requestPayload.prompt)
  selectedTurnJobId.value = String(job.value.id)
  draftDocument.value = discussionMode.value || requestPayload.executionMode === 'direct'
    ? null : cloneRuntimeValue(sourceContext.value?.document) || null
  proposal.value = null
  proposalError.value = ''
  diffConfirmed.value = false
  if (persistActiveJob()) clearDurableAttempt('create', attemptKey)
  else {
    restoreDurableAttemptNotice()
    ElMessage.warning('任务已创建；恢复指针未写入，请保持当前页面，原请求号仍可用于恢复')
  }
  if (isTerminalStatus(job.value.status)) schedulePoll(0, true)
  else if (recoverExisting && isDirectExecutionJob()) return resumeRestoredDirectJob(job.value.id)
  else beginJobMonitoring({ resetCursor: true })
  return true
}

async function submitJob() {
  if (actionBusy.value || livePreviewCanvasMutationBlocked.value) return
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
  if (nativeModelConfigurationIssue.value) return ElMessage.warning(nativeModelConfigurationIssue.value)
  submissionStartedAt.value = Date.now()
  submitting.value = true
  const identity = beginActionIdentity('create', { jobId: null })
  let preparationId = null
  let recoverCreation = null
  let creationRequestStarted = false
  let creationResponseReceived = false
  let reusedPersistedAttempt = false
  try {
    const source = await buildSource()
    assertActionIdentity(identity)
    const directExecution = Boolean(
      !discussionMode.value
      && source.type === 'cloud_document'
      && !sourceContext.value?.readonly,
    )
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
        generationMode: form.generationMode,
      },
      source,
      target: discussionMode.value ? 'message' : directExecution ? 'file' : (
        ['none', 'uploaded_artifact'].includes(source.type)
        || sourceContext.value?.readonly
      ) ? 'file' : 'proposal',
      // 云端可编辑脑图走后台直写；本地快照/上传文件仍使用旧的
      // Artifact/Proposal 预览契约，避免把浏览器私有状态误当成权威正文。
      executionMode: directExecution ? 'direct' : 'preview',
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
    const persistedAttemptKey = readPersistedAttempts().create?.key
    submitAttempt = await resolveDurableAttempt('create', submitAttempt, requestPayload, {
      createKey: () => createMindmapAiIdempotencyKey(),
      metadata: {
        sourceType: source.type,
        sourceDocumentId: sourceContext.value?.documentId || null,
        sourceMindmapId: sourceContext.value?.mindmapId || null,
        sourceRevision: sourceContext.value?.revision ?? null,
        sourceFingerprint: sourceFingerprint.value || '',
        configuration: requestConfiguration,
        // Cloud sources contain an ID, not a private document snapshot. Keep
        // the exact payload so recovery can replay the same idempotent request
        // even when GET reconciliation races an uncommitted original POST.
        requestPayload: directExecution ? requestPayload : undefined,
      },
    })
    reusedPersistedAttempt = submitAttempt.key === persistedAttemptKey
    assertActionIdentity(identity)
    const attemptKey = submitAttempt.key
    if (directExecution) {
      // Fence every cloud writer BEFORE the request can start backend work.
      // Otherwise the first Yjs/revision message can paint a complete node
      // before the browser has even received the new job id.
      preparationId = await prepareDirectCanvasRequest(attemptKey, { drainLocalChanges: !reusedPersistedAttempt })
      assertActionIdentity(identity)
    }
    const activation = { identity, requestPayload, requestConfiguration, attemptKey, preparationId,
      recoverExisting: reusedPersistedAttempt }
    recoverCreation = async () => {
      let response
      try { response = await reconcileMindmapAiJob(attemptKey) }
      catch (error) {
        if (!isHttpNotFound(error)) throw error
        // A 404 may overtake the original POST's transaction. Replay exactly
        // the same key/payload; never translate an unknown result into unlock.
        response = await createMindmapAiJob(requestPayload, attemptKey)
      }
      return activateCreatedJob(response.data, { ...activation, recoverExisting: true })
    }
    creationRequestStarted = true
    const response = await createMindmapAiJob(requestPayload, attemptKey)
    creationResponseReceived = true
    await activateCreatedJob(response.data, activation)
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return false
    if (!creationRequestStarted || (!creationResponseReceived && !reusedPersistedAttempt && isDefinitiveAiCreationRejection(error))) {
      if (!reusedPersistedAttempt) {
        clearDurableAttempt('create', submitAttempt?.key)
        submitAttempt = null
      }
      ElMessage.error(formatMindmapAiError(error, 'AI 脑图任务创建被拒绝'))
      return
    }
    if (preparationId && recoverCreation && directCanvasOwnerId.value === preparationId) {
      uncertainCanvasCreation.value = { preparationId, recover: recoverCreation }
      await reconcilePendingCanvasCreation()
      return
    }
    ElMessage.error(formatMindmapAiError(error, 'AI 脑图任务创建失败'))
  } finally {
    await releaseCanvasPreparation(preparationId)
    submitting.value = false
    submissionStartedAt.value = 0
  }
}

async function activateFollowupJob(nextJob, {
  identity,
  requestPayload,
  attemptKey,
  preparationId,
  initialPreview = null,
  recoverExisting = false,
}) {
  assertActionIdentity(identity)
  await adoptDirectCanvasRequest(nextJob, preparationId)
  assertActionIdentity(identity)
  const previousDraft = cloneRuntimeValue(draftDocument.value)
  stopPolling()
  stopRealtime('idle')
  job.value = nextJob
  monitoringSuspendedJobId = ''
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
  pendingFollowupPrompt.value = ''
  proposal.value = null
  proposalError.value = ''
  diffConfirmed.value = false
  draftDocument.value = null
  const pointerPersisted = persistActiveJob()
  if (pointerPersisted) clearDurableAttempt('followup', attemptKey)
  followupAttempt = null
  restoreDurableAttemptNotice()
  // The child has its own cursor and draft. Start it before fetching the full
  // conversation, otherwise the parent remains the only visible activity
  // during the extra timeline round trip.
  if (isTerminalStatus(job.value.status)) schedulePoll(0, true)
  else if (recoverExisting && isDirectExecutionJob()) {
    resetCurrentJobCursor(job.value.id)
    latestPreviewVersion.value = -1
    latestPreviewEpoch.value = 1
    if (!(await resumeRestoredDirectJob(job.value.id))) return false
  }
  else {
    // A direct queued child's older SSE events must not replay over the cloud
    // baseline captured after its parent committed. Establish the latest
    // checkpoint floor before subscribing, then preserve those coordinates.
    if (initialPreview) {
      resetCurrentJobCursor(job.value.id)
      latestPreviewVersion.value = -1
      latestPreviewEpoch.value = 1
      if (!acceptDraftPreview(initialPreview)) throw new Error('下一轮最新草稿无法建立恢复起点')
    }
    beginJobMonitoring({ resetCursor: !initialPreview })
  }
  void restoreSessionTimeline(job.value.sessionId, {
    expectedJobId: job.value.id,
    recoveryGeneration: restoreGeneration,
  })
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
  preparationId,
  recoverExisting = false,
}) {
  assertActionIdentity(identity)
  await adoptDirectCanvasRequest(nextJob, preparationId)
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
  if (isTerminalStatus(job.value.status)) schedulePoll(0, true)
  else if (recoverExisting && isDirectExecutionJob()) {
    resetCurrentJobCursor(job.value.id)
    latestPreviewVersion.value = -1
    latestPreviewEpoch.value = 1
    if (!(await resumeRestoredDirectJob(job.value.id))) return false
  }
  else beginJobMonitoring({ resetCursor: true })
  if (!pointerPersisted) {
    ElMessage.warning('重试任务已创建；请保持当前页面，原请求号仍可用于恢复')
  }
  return true
}

async function retryJob() {
  const retriedJob = job.value
  if (actionBusy.value || livePreviewCanvasMutationBlocked.value || !retryAvailable.value || !retriedJob?.id) {
    if (livePreviewCanvasMutationBlocked.value) {
      ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再重试任务')
    }
    return false
  }
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
  if (nativeModelConfigurationIssue.value) return ElMessage.warning(nativeModelConfigurationIssue.value)
  retrying.value = true
  const identity = beginActionIdentity('retry', { jobId: retriedJob.id })
  let preparationId = null
  let durableRetryAttempt = null
  let retryRequestStarted = false
  let retryResponseReceived = false
  let reusedPersistedAttempt = false
  try {
    const requestPayload = {
      agentKey: form.agentKey,
      modelId: form.agentKey === 'native_mindmap' ? form.modelId : undefined,
      prompt: retryPrompt.value.trim() || undefined,
      parameters: {
        language: jobConfiguration.value?.language || form.language,
        layout: jobConfiguration.value?.layout || form.layout,
        generationMode: jobConfiguration.value?.generationMode || form.generationMode,
      },
    }
    const knownMaxTurnIndex = Math.max(
      Number(retriedJob.turnIndex || 0),
      ...sessionTurns.value.map(turn => Number(turn?.job?.turnIndex || 0)),
    )
    const persistedAttemptKey = readPersistedAttempts().retry?.key
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
    reusedPersistedAttempt = retryAttempt.key === persistedAttemptKey
    durableRetryAttempt = readPersistedAttempts().retry
    assertActionIdentity(identity)
    const attemptKey = retryAttempt.key
    if (isDirectExecutionJob(retriedJob)) {
      preparationId = await prepareDirectCanvasRequest(attemptKey, { drainLocalChanges: !reusedPersistedAttempt })
    }
    assertActionIdentity(identity)
    retryRequestStarted = true
    const response = await retryMindmapAiJob(
      retriedJob.id,
      requestPayload,
      retryAttempt.key,
    )
    retryResponseReceived = true
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
      preparationId,
      recoverExisting: reusedPersistedAttempt,
    })
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    if (!retryRequestStarted || (!retryResponseReceived && !reusedPersistedAttempt && isDefinitiveAiCreationRejection(error))) {
      if (!reusedPersistedAttempt) {
        clearDurableAttempt('retry', retryAttempt?.key)
        retryAttempt = null
      }
      ElMessage.error(formatMindmapAiError(error, 'AI 脑图重试任务创建被拒绝'))
      return
    }
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
          preparationId,
          recoverExisting: true,
        })
        ElMessage.warning('重试请求已由原请求号精确恢复')
        return
      }
    } catch (recoveryError) {
      if (recoveryError?.code === 'AI_ACTION_SUPERSEDED') return
    }
    if (preparationId && directCanvasOwnerId.value === preparationId && durableRetryAttempt) {
      uncertainCanvasCreation.value = {
        preparationId,
        recover: async () => {
          const recoveredRetry = await replayRetryAttempt(durableRetryAttempt, retriedJob.sessionId)
          return recoveredRetry && activateRetryJob(recoveredRetry, {
            identity, requestPayload: durableRetryAttempt.requestPayload,
            attemptKey: durableRetryAttempt.key, retryOfJob: retriedJob, preparationId,
            recoverExisting: true,
          })
        },
      }
      livePreviewError.value = '重试请求结果尚未确认，已保持脑图只读；恢复连接后可按原请求号确认'
      return
    }
    ElMessage.error(formatMindmapAiError(error, 'AI 脑图重试任务创建失败'))
  } finally {
    await releaseCanvasPreparation(preparationId)
    retrying.value = false
  }
}

async function continueJob() {
  const parentJob = followupParentJob.value
  if (
    actionBusy.value
    || livePreviewCanvasMutationBlocked.value
    || !parentJob?.id
    || (
      !parentJob.artifactId
      && parentJob.status !== 'needs_input'
      && !(isMindmapAiMessageJob(parentJob) && parentJob.status === 'completed_message')
      && parentJob.status !== 'completed_direct'
    )
    || !followupPrompt.value.trim()
  ) {
    if (livePreviewCanvasMutationBlocked.value) {
      ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再继续生成')
    }
    return false
  }
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
  if (nativeModelConfigurationIssue.value) return ElMessage.warning(nativeModelConfigurationIssue.value)
  continuing.value = true
  const identity = beginActionIdentity('followup', { jobId: job.value?.id })
  let preparationId = null
  const parentTurnIndex = Number(parentJob.turnIndex || 0)
  pendingFollowupPrompt.value = followupPrompt.value.trim()
  const monitoredJobId = String(job.value?.id || '')
  // Freeze the currently monitored turn as soon as the user submits another.
  // A delayed poll or draft response must not repaint its old result.
  monitoringSuspendedJobId = monitoredJobId
  invalidateRestoreOperations()
  stopPolling()
  stopRealtime('idle')
  clearTimeout(terminalHydrationRetryTimer)
  terminalHydrationRetryTimer = null
  let durableFollowupAttempt = null
  let followupRequestStarted = false
  let followupResponseReceived = false
  let reusedPersistedAttempt = false
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
    const persistedAttemptKey = readPersistedAttempts().followup?.key
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
    reusedPersistedAttempt = followupAttempt.key === persistedAttemptKey
    const persistedFollowupAttempt = readPersistedAttempts().followup
    durableFollowupAttempt = persistedFollowupAttempt
      ? { ...persistedFollowupAttempt, requestPayload }
      : null
    assertActionIdentity(identity)
    const attemptKey = followupAttempt.key
    if (continuationBase === 'current_document' && !discussionMode.value && sourceContext.value?.readonly !== true) {
      preparationId = await prepareDirectCanvasRequest(attemptKey, { drainLocalChanges: !reusedPersistedAttempt })
    }
    assertActionIdentity(identity)
    followupRequestStarted = true
    const response = await continueMindmapAiJob(
      parentJobId,
      requestPayload,
      followupAttempt.key,
    )
    followupResponseReceived = true
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
      preparationId,
      recoverExisting: reusedPersistedAttempt,
    })
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    if (!followupRequestStarted || (!followupResponseReceived && !reusedPersistedAttempt && isDefinitiveAiCreationRejection(error))) {
      if (!reusedPersistedAttempt) {
        clearDurableAttempt('followup', followupAttempt?.key)
        followupAttempt = null
      }
      ElMessage.error(formatMindmapAiError(error, '继续调整任务创建被拒绝'))
      return
    }
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
          preparationId,
          recoverExisting: true,
        })
        ElMessage.warning('继续生成请求已由原请求号精确恢复')
        return
      }
    } catch (recoveryError) {
      if (recoveryError?.code === 'AI_ACTION_SUPERSEDED') return
    }
    if (preparationId && directCanvasOwnerId.value === preparationId && durableFollowupAttempt) {
      uncertainCanvasCreation.value = {
        preparationId,
        recover: async () => {
          const recoveredChild = await replayFollowupAttempt(durableFollowupAttempt, parentJob.sessionId)
          return recoveredChild && activateFollowupJob(recoveredChild, {
            identity, requestPayload: durableFollowupAttempt.requestPayload,
            attemptKey: durableFollowupAttempt.key, preparationId,
            recoverExisting: true,
          })
        },
      }
      livePreviewError.value = '继续生成请求结果尚未确认，已保持脑图只读；恢复连接后可按原请求号确认'
      return
    }
    ElMessage.error(formatMindmapAiError(error, '继续调整任务创建失败'))
  } finally {
    await releaseCanvasPreparation(preparationId)
    pendingFollowupPrompt.value = ''
    if (monitoringSuspendedJobId === monitoredJobId) {
      monitoringSuspendedJobId = ''
      if (String(job.value?.id || '') === monitoredJobId) schedulePoll(0, true)
    }
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再切换当前脑图')
    return
  }
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再替换当前脑图')
    return
  }
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再插入 AI 分支')
    return
  }
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再保存为云端脑图')
    return
  }
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
      jobId: intent.jobId,
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

function flushPendingCloudMutationIntents({ allowDuringLivePreview = false } = {}) {
  const ownerUserId = currentAiOwnerUserId()
  if (!ownerUserId) {
    updateCloudMutationRecoveryNotice()
    return Promise.resolve({ settled: [], failures: [] })
  }
  const activeFlush = cloudMutationFlushPromises.get(ownerUserId)
  if (activeFlush) return activeFlush
  if (livePreviewCanvasMutationBlocked.value && !allowDuringLivePreview) {
    updateCloudMutationRecoveryNotice()
    return Promise.resolve({ settled: [], failures: [], deferred: true })
  }
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
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再同步云端 AI 操作')
    return { settled: [], failures: [], deferred: true }
  }
  const result = await flushPendingCloudMutationIntents()
  if (!result.failures.length && result.settled.length) {
    ElMessage.success('云端 AI 操作已与权威画布同步')
  }
  return result
}

async function discardPermanentCloudMutationRecovery() {
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再清除云端恢复记录')
    return false
  }
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
  previewJobId = '',
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
  const context = await requestEditorContext({ previewJobId })
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
    aiPreviewJobId: previewJobId,
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
  previewJobId = '',
}) {
  const context = await requestEditorContext({ previewJobId })
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

async function rejectReviewProposal() {
  const proposalId = String(job.value?.proposalId || proposal.value?.id || '')
  const jobId = String(job.value?.id || '')
  if (!proposalId || !jobId || rejectingReview.value) return false
  rejectingReview.value = true
  const identity = beginActionIdentity('reject-review', { jobId, proposalId })
  try {
    const response = await rejectMindmapAiProposal(proposalId)
    assertActionIdentity(identity)
    const nextJob = response?.data
    if (!nextJob || String(nextJob.id || jobId) !== jobId) {
      throw new Error('服务端未返回可确认的 AI 拒绝状态')
    }
    job.value = mergeMindmapAiJobSnapshot(job.value, nextJob)
    if (job.value.status === 'rejected') {
      proposal.value = proposal.value
        ? { ...proposal.value, status: 'rejected' }
        : proposal.value
      stopRealtime('completed')
      stopPolling()
      emitAiCanvasPreviewEvent({ phase: 'clear', jobId })
      upsertSessionTurn(job.value)
      persistActiveJob()
      await refreshTimelineAfterSideEffect(identity)
      ElMessage.success('本轮 AI 结果已不采纳，已恢复生成前内容')
    } else if (['applied', 'undone'].includes(job.value.status)) {
      upsertSessionTurn(job.value)
      persistActiveJob()
      await refreshTimelineAfterSideEffect(identity)
      ElMessage.info(job.value.status === 'applied' ? '本轮结果已被采纳' : '本轮结果已被撤销')
    }
    return true
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return false
    schedulePoll(0, true)
    ElMessage.error(formatMindmapAiError(error, '不采纳 AI 结果失败，请重试'))
    return false
  } finally {
    rejectingReview.value = false
  }
}

async function rejectLiveDraft() {
  if (!canRejectLiveDraft.value && !highImpactReviewRequired.value) return false
  const jobId = String(job.value?.id || '')
  const wasRunning = running.value
  if (wasRunning) {
    // Keep cancellation controls locked while the in-flight renderer and
    // revert request drain. The current canvas remains visible during rollback.
    cancelling.value = true
  }
  const reverted = await revertLiveDraftPreview()
  if (!reverted) {
    if (wasRunning) cancelling.value = false
    ElMessage.error(livePreviewError.value || 'AI 实时预览撤回失败，请在面板重试')
    return false
  }
  // A terminal hydration or page reload must not silently reapply a result
  // the user has already rejected. A new follow-up/reset clears this fence.
  livePreviewSuppressedJobId = jobId
  persistLivePreviewSuppression(jobId)
  // Both a normal ready result and a high-impact review are persisted
  // proposals.  Reverting the local preview alone is not enough: without a
  // server-side rejection a reload/another tab can still apply the ready
  // proposal (and the default-accept path may resurrect it).
  if (['ready', 'needs_review'].includes(job.value?.status) && job.value?.proposalId) {
    return await rejectReviewProposal()
  }
  if (wasRunning) {
    if (!(await cancelJob({ previewAlreadyReverted: true, initiatedByReject: true }))) {
      ElMessage.warning('画布预览已撤回，但任务可能仍在运行；请在 AI 面板重试取消')
      return true
    }
  }
  ElMessage.info('AI 实时变更已撤回')
  return true
}

async function onAiCanvasDraftAction(payload = {}, request = {}) {
  const jobId = String(payload.jobId || '')
  if (payload.action === 'undo') {
    if (!componentAlive || !jobId || String(job.value?.id || '') !== jobId
      || !canUndoCurrentProposal.value) {
      request.resolve?.(false)
      return
    }
    try {
      if (!visible.value) visible.value = true
      request.resolve?.(await undoProposal())
    } catch (error) {
      request.reject?.(error)
    }
    return
  }
  if (
    !componentAlive
    || !livePreviewActive.value
    || !jobId
    || String(job.value?.id || '') !== jobId
    || livePreviewJobId !== jobId
  ) {
    request.resolve?.(false)
    return
  }
  try {
    if (payload.action === 'pause' || payload.action === 'resume') {
      request.resolve?.(toggleLivePreviewPlayback(payload.action === 'pause'))
      return
    }
    if (payload.action === 'reject') {
      if (!canRejectLiveDraft.value) {
        ElMessage.info('当前 AI 操作正在处理，请稍后再撤回')
        request.resolve?.(false)
        return
      }
      request.resolve?.(await rejectLiveDraft())
      return
    }
    if (payload.action === 'apply') {
      if (!canApplyLiveCanvasDraft.value) {
        ElMessage.info('请先查看并确认 AI 提案差异')
        request.resolve?.(false)
        return
      }
      request.resolve?.(await applyProposal())
      return
    }
    if (payload.action === 'retry-accept') {
      request.resolve?.(await acceptCompletedLivePreviewByDefault(jobId, { retry: true }))
      return
    }
    if (payload.action === 'review') {
      if (!visible.value) visible.value = true
      await nextTick()
      if (!componentAlive || job.value?.id !== jobId || livePreviewJobId !== jobId) {
        request.resolve?.(false)
        return
      }
      const review = proposalReviewRef.value
      if (review) review.open = true
      const target = review || activityTimelineRef.value || livePreviewNoticeRef.value
      target?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
      target?.focus?.({ preventScroll: true })
      request.resolve?.(true)
      return
    }
    request.resolve?.(false)
  } catch (error) {
    request.reject?.(error)
  }
}

function onAiAcceptedUndoRequested(payload = {}) {
  if (
    !componentAlive
    || !['applied', 'completed_direct', 'failed', 'stale', 'cancelled'].includes(job.value?.status)
    || !canUndoCurrentProposal.value
    || (payload.jobId && String(payload.jobId) !== String(job.value.id))
    || (payload.proposalId && payload.proposalId !== job.value.proposalId)
  ) return
  if (!visible.value) visible.value = true
  void undoProposal()
}

async function applyProposal({ automatic = false } = {}) {
  if (actionBusy.value) return false
  if (sourceBaselineMismatch.value) {
    ElMessage.warning('当前脑图已发生变化，请基于最新内容重新生成后再采纳')
    return false
  }
  if (livePreviewCatchingUp.value || livePreviewPreparing.value) {
    ElMessage.info('AI 实时画布正在补齐，完成后再采纳')
    return false
  }
  const currentJob = job.value
  const currentProposal = proposal.value
  if (!currentProposal || (!automatic && !diffConfirmed.value)) {
    if (!automatic) ElMessage.warning('请先查看并勾选提案差异确认，再应用到当前脑图')
    if (currentProposal && !automatic) {
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
  let previewJobId = ''
  const acceptedPreviewNodeCount = livePreviewRenderedNodeCount.value
  const acceptedPreviewTargetNodeCount = livePreviewTargetNodeCount.value
  const acceptedPreviewChangeSummary = livePreviewChangeSummary.value
    ? { ...livePreviewChangeSummary.value }
    : null
  try {
    previewJobId = await holdLiveDraftPreviewForApply(jobId)
    const result = sourceMindmapId
      ? await applyCloudProposal({
          proposalId,
          sourceMindmapId,
          baseRevision: currentJob.baseRevision,
          baseHash: currentJob.baseHash,
          baseRoomEpoch: currentJob.baseRoomEpoch,
          actionIdentity: identity,
          forceOverwrite: directCloudOverwrite,
          previewJobId,
        })
      : await applyLocalProposal({
          proposalId,
          expectedSourceFingerprint,
          actionIdentity: identity,
          previewJobId,
        })
    finishLiveDraftPreviewAfterApply(jobId)
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
    if (job.value.status === 'applied' && canUndoCurrentProposal.value) {
      emitAiCanvasPreviewEvent({
        phase: 'accepted',
        jobId,
        message: automatic ? 'AI 结果已保存' : 'AI 结果已确认保存',
        nodeCount: acceptedPreviewNodeCount,
        targetNodeCount: acceptedPreviewTargetNodeCount,
        changeSummary: acceptedPreviewChangeSummary,
      })
    }
    if (sourceMindmapId && job.value.status === 'undone') {
      ElMessage.warning('AI 提案曾成功应用，但已被后续撤销；当前画布已同步权威版本')
    } else if (result?.receiptUnstored) {
      ElMessage.warning('提案已应用但回执未保存；请恢复网络后重新打开 AI 面板重试')
    } else if (result?.receiptPending) {
      ElMessage.warning('提案已应用；回执因网络问题排队，联网后会自动补发')
    } else if (automatic) {
      ElMessage.success('AI 结果已保存；如需恢复可撤销本轮 AI 修改')
    } else if (directCloudOverwrite) {
      ElMessage.success('AI 完整结果已覆盖当前脑图，可随时撤销')
    } else {
      ElMessage.success('AI 脑图提案已应用')
    }
    return true
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return
    let reconciled = null
    try {
      reconciled = await reconcileJobAfterSideEffect(identity)
    } catch (reconcileError) {
      console.warn('AI 应用状态暂未完成对账:', reconcileError)
    }
    if (reconciled?.status === 'applied') {
      // The server may have committed while the editor reload was still in
      // flight. Keep the accepted result visible until the editor converges;
      // reverting here would briefly put an already-committed cloud document
      // back on the old local baseline.
      finishLiveDraftPreviewAfterApply(jobId)
      if (canUndoCurrentProposal.value) {
        emitAiCanvasPreviewEvent({ phase: 'accepted', jobId, message: 'AI 结果已采纳' })
      }
      if (sourceMindmapId) {
        ElMessage.warning('提案已由服务端应用；编辑器正在恢复权威版本，请稍后重试同步。')
      }
      return true
    }
    if (automatic && livePreviewActive.value && livePreviewJobId === String(jobId)) {
      // A failed automatic commit is not a user undo. Keep the visible final
      // result and its pre-AI baseline available for retry or explicit undo.
      if (livePreviewApplyingJobId === String(jobId)) livePreviewApplyingJobId = ''
    } else if (livePreviewActive.value && livePreviewJobId === String(jobId)) {
      await revertLiveDraftPreview()
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
  if (actionBusy.value || !canUndoCurrentProposal.value) return false
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
    emitAiCanvasPreviewEvent({ phase: 'clear', jobId })
    ElMessage.success('本次 AI 应用已撤销')
    return true
  } catch (error) {
    if (error === 'cancel' || error === 'close') return false
    if (error?.code === 'AI_ACTION_SUPERSEDED') return false
    const reconciled = await reconcileJobAfterSideEffect(identity)
    if (reconciled?.status === 'undone') {
      emitAiCanvasPreviewEvent({ phase: 'clear', jobId })
      ElMessage.warning('撤销请求已提交，已从服务端恢复撤销状态')
      return true
    }
    ElMessage.error(formatMindmapAiError(error, 'AI 应用撤销失败'))
    return false
  } finally {
    undoing.value = false
  }
}

async function cancelJob({ previewAlreadyReverted = false, initiatedByReject = false } = {}) {
  const jobId = job.value?.id
  if (!jobId || (actionBusy.value && !initiatedByReject)) return false
  const preserveDraft = Boolean(!previewAlreadyReverted && livePreviewActive.value)
  cancelling.value = true
  const identity = beginActionIdentity('cancel', { jobId })
  try {
    const response = await cancelMindmapAiJob(jobId, { preserveDraft })
    assertActionIdentity(identity)
    job.value = mergeMindmapAiJobSnapshot(job.value, response.data)
    realtimeError.value = ''
    persistActiveJob()
    if (isTerminalStatus(job.value.status)) {
      if (!(await finalizeTerminalJob(jobId, { retry: true, refresh: false }))) return false
      // Settlement can hand the canvas to a queued successor. The parent's
      // cancellation must not stop that child's stream or its only terminal
      // drain timer, nor attempt to revert/hydrate the child's state.
      if (!componentAlive || job.value?.id !== jobId) return true
      await refreshTimelineAfterSideEffect(identity)
      return true
    }
    schedulePoll(200)
    return true
  } catch (error) {
    if (error?.code === 'AI_ACTION_SUPERSEDED') return false
    ElMessage.error(formatMindmapAiError(error, '取消任务失败'))
    return false
  } finally {
    cancelling.value = false
  }
}

async function deleteSessionRecord() {
  const sessionId = job.value?.sessionId
  if (!sessionId || actionBusy.value) return
  if (livePreviewCanvasMutationBlocked.value) {
    ElMessage.info('请先采纳或不采纳当前 AI 实时预览，再删除会话记录')
    return
  }
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
    // This exact session is durably deleted; no SSE terminal event is required
    // to detach its local callbacks. Ordinary running-task resets stay blocked.
    resetNewJob({ clearStoredJob: true, preserveForm: true, detach: true })
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
  resetNewJob({ clearStoredJob: false, preserveForm: true, detach: true })
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

watch(pendingFollowupPrompt, async (prompt) => {
  if (!prompt) return
  const currentTimeline = activityTimelineRef.value
  const shouldFollowLatest = !currentTimeline
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

function emitAiEditingState() {
  const aiCanvasTask = Boolean(
    job.value?.id
    && form.sourceMode === 'current'
    && !messageModeActive.value
    && !viewingHistoricalArtifact.value
    && sourceContext.value?.readonly !== true
    && (
      running.value
      || livePreviewActive.value
      || livePreviewRendering.value
      || livePreviewReverting.value
      || livePreviewAutoAccepting.value
      || applying.value
      || cancelling.value
    )
  )
  bus.emit('aiEditingState', {
    jobId: String(job.value?.id || ''),
    // A terminal status alone cannot unlock direct tasks: canvas ownership
    // lasts until playback drains and the authoritative baseline is settled.
    locked: aiCanvasTask || preparingCanvas.value || directCanvasOwned.value,
  })
}

watch(
  [
    () => running.value,
    preparingCanvas,
    directCanvasOwned,
    livePreviewEligible,
    livePreviewActive,
    livePreviewRendering,
    livePreviewReverting,
    livePreviewAutoAccepting,
    applying,
    cancelling,
    () => job.value?.status,
  ],
  emitAiEditingState,
  { immediate: true },
)
watch(livePreviewCanvasMutationBlocked, (blocked, wasBlocked) => {
  if (componentAlive && wasBlocked && !blocked) void flushPendingCloudMutationIntents()
})

async function onNetworkOnline() {
  if (uncertainCanvasCreation.value) await reconcilePendingCanvasCreation()
  await flushPendingCloudMutationIntents()
  await flushLocalApplyAcks()
  try { await requestEditorContext() } catch {}
  if (terminalHydrationState.value === 'error' && isTerminalStatus(job.value?.status)) {
    retryTerminalHydration()
  }
  if (job.value?.status === 'ready'
    && livePreviewAutoAcceptFailedJobId.value === String(job.value.id)) {
    void acceptCompletedLivePreviewByDefault(job.value.id, { retry: true })
  }
  if (running.value && job.value?.id) {
    if (directCanvasRecoveryJobId.value === String(job.value.id)) {
      // Reconnection is subject to the same latest-checkpoint barrier as an
      // explicit retry. Online events must not reopen historical SSE while a
      // failed/in-flight restoration still has no safe playback floor.
      if (!restoringJob.value) await retryLivePreviewSync()
      return
    }
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
  finishCompletedAiGeneration,
})

onMounted(() => {
  bus.on('showAiMindmap', showDialog)
  bus.on('mindmapEditorReady', restoreActiveJobWhenEditorReady)
  bus.on('aiCanvasDraftAction', onAiCanvasDraftAction)
  bus.on('aiAcceptedUndoRequested', onAiAcceptedUndoRequested)
  bus.on('aiCloudMutationRecoveryReady', onCloudMutationRecoveryReady)
  bus.on('aiLocalJournalRecovered', onLocalAiJournalRecovered)
  bus.on('aiEditingStateRequest', emitAiEditingState)
  bus.on('node_active', onEditorNodeActive)
  window.addEventListener('online', onNetworkOnline)
  window.addEventListener('offline', onNetworkOffline)
  window.addEventListener('mindmap-ai-open-task', onDeepLinkedAiTask)
  void flushPendingCloudMutationIntents()
  void flushLocalApplyAcks()
})

onBeforeUnmount(() => {
  componentAlive = false
  clearLivePreviewAnnouncement()
  // Route exit leaves the durable server job running; it is not completion or
  // rejection, and must never initiate an authoritative settlement.
  resetNewJob({ clearStoredJob: false, preserveForm: true, detach: true })
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
  bus.off('mindmapEditorReady', restoreActiveJobWhenEditorReady)
  bus.off('aiCanvasDraftAction', onAiCanvasDraftAction)
  bus.off('aiAcceptedUndoRequested', onAiAcceptedUndoRequested)
  bus.off('aiCloudMutationRecoveryReady', onCloudMutationRecoveryReady)
  bus.off('aiLocalJournalRecovered', onLocalAiJournalRecovered)
  bus.off('aiEditingStateRequest', emitAiEditingState)
  bus.off('node_active', onEditorNodeActive)
  window.removeEventListener('online', onNetworkOnline)
  window.removeEventListener('offline', onNetworkOffline)
  window.removeEventListener('mindmap-ai-open-task', onDeepLinkedAiTask)
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
.controlPane {
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

.activityEmpty {
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
  display: block;
  min-height: 0;
}

.controlPane {
  padding: 14px;
  overflow: auto;
}

.formGrid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

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

.proposalPreview {
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

.diffCounts {
  display: flex;
  flex-wrap: wrap;
  font-size: 13px;
  font-weight: 600;
  gap: 8px 16px;

  &.is-unavailable {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    font-weight: 400;
  }
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

  .workspaceMain { overflow: auto; }

  .controlPane { overflow: visible; }
}

@media (prefers-reduced-motion: reduce) {
  .connectionBadge i { animation: none !important; }
}

@media (max-width: 760px) {
  .aiDialogBody {
    height: auto;
    grid-template-columns: 1fr;
  }

  .activitySidebar { max-height: 250px; }

  .workspaceMain { overflow: visible; }

  .formGrid { grid-template-columns: 1fr; }
}
</style>

<style lang="scss">
/* XMind 风格的 AI 工作台：对话和当前编辑画布保持在同一工作区。 */
.mindmapAiDrawer {
  --el-color-primary: #7a5af8;
  --el-color-primary-light-9: #f2efff;
  --ai-panel-bg: #f4f5f7;
  --ai-card-bg: #ffffff;
  --ai-ink: #20211f;
  --ai-muted: #72746f;
  --ai-border: rgba(25, 28, 24, 0.1);
  --ai-soft-bg: #f0f1ed;
  --ai-soft-hover: #e8e9e4;
  --ai-audit-bg: #f6f7f4;
  --ai-welcome-start: #ffffff;
  --ai-welcome-end: #eee9ff;
  --ai-live-bg: #f2efff;
  --ai-live-border: rgba(122, 90, 248, 0.2);
  --ai-live-dot: #7a5af8;
  --ai-live-complete-bg: #f2fbf5;
  --ai-live-complete-border: rgba(47, 158, 96, 0.24);
  --ai-live-complete-dot: #2f9e60;
  --ai-action-bg: #faf9ff;
  --ai-control-border: rgba(25, 28, 24, 0.16);
  height: 100% !important;
  background: var(--ai-panel-bg);
  box-shadow: 10px 0 34px rgba(20, 24, 20, 0.12);

  &.isDark {
    --el-color-primary-light-9: #302956;
    --ai-panel-bg: #1d2025;
    --ai-card-bg: #25282d;
    --ai-ink: #edf0f4;
    --ai-muted: #a9b0ba;
    --ai-border: rgba(255, 255, 255, 0.12);
    --ai-soft-bg: #30343b;
    --ai-soft-hover: #3a4048;
    --ai-audit-bg: #2b2f35;
    --ai-welcome-start: #2d2945;
    --ai-welcome-end: #25282d;
    --ai-live-bg: #302956;
    --ai-live-border: rgba(169, 144, 255, 0.36);
    --ai-live-dot: #b29bff;
    --ai-live-complete-bg: #21382b;
    --ai-live-complete-border: rgba(103, 211, 142, 0.34);
    --ai-live-complete-dot: #67d38e;
    --ai-action-bg: #2b2745;
    --ai-control-border: rgba(255, 255, 255, 0.16);
    box-shadow: 10px 0 34px rgba(0, 0, 0, 0.34);
  }

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

.tagSuggestions {
  display: grid;
  padding: 9px 10px;
  border: 1px solid var(--ai-border);
  border-radius: 8px;
  background: var(--ai-soft-bg);
  color: var(--ai-ink);
  font-size: 12px;
  gap: 6px;

  p { margin: 0; line-height: 1.5; overflow-wrap: anywhere; }
  strong { overflow-wrap: anywhere; }
  > p, small { color: var(--ai-muted); font-size: 11px; }
  ul { display: grid; margin: 0; padding-left: 17px; gap: 7px; }
}

.usageSummary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;

  span {
    padding: 3px 7px;
    border-radius: 999px;
    color: var(--ai-muted);
    background: var(--ai-soft-bg);
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
      background: var(--ai-audit-bg);
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
    background: linear-gradient(145deg, var(--ai-welcome-start), var(--ai-welcome-end));
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

.liveDraftNotice {
  display: flex;
  margin-bottom: 12px;
  padding: 10px 11px;
  align-items: flex-start;
  border: 1px solid rgba(122, 90, 248, 0.2);
  border-radius: 10px;
  color: var(--ai-ink);
  border-color: var(--ai-live-border);
  background: var(--ai-live-bg);
  gap: 9px;

  > i {
    width: 8px;
    height: 8px;
    margin-top: 4px;
    flex: 0 0 auto;
    border-radius: 50%;
    background: var(--ai-live-dot);
    animation: aiPulse 1.2s ease-in-out infinite;
  }

  > div {
    display: grid;
    min-width: 0;
    gap: 2px;
  }

  strong { font-size: 12px; }
  span { color: var(--ai-muted); font-size: 11px; line-height: 1.45; }

  .livePreviewPlaybackButton {
    margin-left: auto;
    flex: 0 0 auto;
    align-self: center;
    padding-inline: 4px;
    font-size: 11px;
  }

  &.is-complete {
    border-color: var(--ai-live-complete-border);
    background: var(--ai-live-complete-bg);

    > i {
      background: var(--ai-live-complete-dot);
      animation: none;
    }
  }

  &.is-direct {
    border-color: color-mix(in srgb, var(--el-color-primary) 28%, transparent);
    background: color-mix(in srgb, var(--el-color-primary) 8%, var(--el-bg-color));
  }
}

.livePreviewRecovery {
  display: flex;
  margin-bottom: 12px;
  padding: 8px 10px;
  align-items: center;
  justify-content: space-between;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 9px;
  color: var(--el-text-color-secondary);
  background: var(--el-color-warning-light-9);
  font-size: 11px;
  line-height: 1.45;
  gap: 10px;

  span { min-width: 0; }
  .el-button { flex: 0 0 auto; }
}

.draftFreshnessRecovery {
  display: grid;
  margin-bottom: 12px;
  gap: 8px;

  > .el-button {
    justify-self: start;
    margin-left: 34px;
  }
}

.mindmapAiSrOnly {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  border: 0;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

.liveDraftAction {
  border-color: rgba(122, 90, 248, 0.22);
  background: var(--ai-action-bg);
}

.aiComposer {
  padding: 10px;
  border: 1px solid var(--ai-control-border);
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

.composerPreflight {
  display: flex;
  margin: 2px 2px 4px;
  align-items: baseline;
  color: var(--ai-muted);
  font-size: 11px;
  line-height: 1.45;
  gap: 6px;
}

.composerPreflightLabel {
  flex: 0 0 auto;
  color: var(--el-color-primary);
  font-weight: 600;
}

.composerRoutePicker {
  display: flex;
  min-height: 28px;
  margin: 2px 0 4px;
  align-items: center;
  flex-wrap: wrap;
  color: var(--ai-muted);
  font-size: 11px;
  gap: 4px;
}

.composerRouteLabel { flex: 0 0 auto; }

.composerRoutePicker button {
  padding: 4px 8px;
  border: 1px solid var(--ai-control-border);
  border-radius: 999px;
  color: var(--ai-muted);
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.composerRoutePicker button:hover:not(:disabled),
.composerRoutePicker button.is-active {
  border-color: color-mix(in srgb, var(--el-color-primary) 48%, var(--ai-control-border));
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 9%, transparent);
}

.composerRoutePicker button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.composerRouteHint {
  flex: 1 1 180px;
  min-width: 150px;
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
  background: var(--ai-soft-bg);
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

  &:hover:not(:disabled) { color: var(--ai-ink); background: var(--ai-soft-hover); }
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
  background: var(--ai-soft-bg);

  button {
    padding: 5px 7px;
    border: 0;
    border-radius: 7px;
    color: var(--ai-muted);
    background: transparent;
    font-size: 11px;
    cursor: pointer;

    &.is-active { color: var(--ai-ink); background: var(--ai-card-bg); box-shadow: 0 1px 3px rgba(20, 24, 20, 0.12); }
    &:disabled { cursor: default; opacity: 0.7; }
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
  .starterGrid button,
  .liveDraftNotice > i { animation: none; transition: none; }
}

@media (max-width: 760px) {
  .mindmapAiDrawer { width: 100% !important; }
  .starterGrid,
  .mindmapAiDrawer .formGrid { grid-template-columns: 1fr; }
  .reasoningModes button { padding-inline: 6px; }
}
</style>
