<template>
  <div class="app-container agentAdminPage">
    <el-alert
      title="Connector 只保存服务端密钥引用，不接收或展示明文密钥。页面内一致性检查仅验证本地确定性合同，不替代真实供应商、安全故障注入与质量发布验收。"
      type="info"
      show-icon
      :closable="false"
      class="pageAlert"
    />

    <el-row :gutter="12" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="Refresh" :loading="loading" @click="loadConnectors">
          刷新
        </el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button
          type="success"
          plain
          icon="CircleCheck"
          :disabled="!selectedRows.length"
          :loading="batchChecking"
          @click="checkSelected"
        >
          检查选中项
        </el-button>
      </el-col>
    </el-row>

    <el-table
      v-loading="loading"
      :data="connectors"
      row-key="agentKey"
      @selection-change="selectedRows = $event"
    >
      <el-table-column type="selection" width="52" />
      <el-table-column label="Agent" min-width="190">
        <template #default="{ row }">
          <div class="agentName">{{ row.displayName }}</div>
          <code>{{ row.agentKey }}</code>
          <div class="muted">Adapter {{ row.manifest?.adapterVersion || '-' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="SDK / 运行时" min-width="200">
        <template #default="{ row }">
          <div>{{ row.manifest?.sdkName || '-' }} {{ row.manifest?.sdkVersion || '' }}</div>
          <div class="muted">{{ row.manifest?.runtimeVersion || '运行时由平台管理' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="发布" width="150" align="center">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">
            {{ row.enabled ? '已启用' : '已停用' }}
          </el-tag>
          <div class="muted rollout">灰度 {{ row.rolloutPercentage }}%</div>
        </template>
      </el-table-column>
      <el-table-column label="健康状态" width="150" align="center">
        <template #default="{ row }">
          <el-tooltip :content="row.healthReason || healthText(row.healthStatus)" placement="top">
            <el-tag :type="statusTagType(row.healthStatus)">{{ healthText(row.healthStatus) }}</el-tag>
          </el-tooltip>
          <div class="muted timeText">{{ displayTime(row.lastHealthTime) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="确定性合同" width="150" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="showConformance(row)">
            <el-tag :type="statusTagType(row.conformanceStatus)">
              {{ conformanceText(row.conformanceStatus) }}
            </el-tag>
          </el-button>
          <div class="muted timeText">{{ displayTime(row.lastConformanceTime) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="数据与网络" min-width="190">
        <template #default="{ row }">
          <div>{{ row.dataRegion || '未指定区域' }}</div>
          <div class="muted">{{ row.networkPolicy === 'deny' ? '禁止 Agent 外部网络' : '遵循 Adapter 默认策略' }}</div>
          <div class="muted">{{ row.credentialConfigured ? '已配置密钥引用' : '未配置密钥引用' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="运行上限" min-width="210">
        <template #default="{ row }">
          <div>${{ row.maxBudgetUsd }} / {{ row.timeoutSeconds }} 秒</div>
          <div class="muted">{{ row.maxNodes }} 节点 · {{ row.maxDepth }} 层</div>
          <div class="muted">最多 {{ row.maxConcurrentJobs }} 个并发任务</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="250" fixed="right" align="center">
        <template #default="{ row }">
          <el-button link type="primary" icon="Edit" @click="openEditor(row)">配置</el-button>
          <el-button
            link
            type="primary"
            :loading="rowBusy(row, 'health')"
            @click="runCheck(row, 'health')"
          >健康检查</el-button>
          <el-button
            link
            type="primary"
            :loading="rowBusy(row, 'conformance')"
            @click="runCheck(row, 'conformance')"
          >确定性检查</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !connectors.length" description="暂无已注册的 Agent Adapter" />

    <el-dialog v-model="editorVisible" title="配置 Agent Connector" width="720px" append-to-body>
      <el-form ref="editorRef" :model="form" :rules="rules" label-width="128px">
        <el-form-item label="Agent">
          <div>
            <strong>{{ editingConnector?.displayName }}</strong>
            <code class="agentKeyInline">{{ editingConnector?.agentKey }}</code>
          </div>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="灰度比例">
          <el-slider v-model="form.rolloutPercentage" :min="0" :max="100" show-input />
          <div class="fieldHint">按用户 ID 稳定分桶；0% 不向用户开放，100% 全量开放。</div>
        </el-form-item>
        <el-form-item label="数据区域" prop="dataRegion">
          <el-input v-model="form.dataRegion" maxlength="64" placeholder="例如 cn、us，留空使用 Adapter 声明" clearable />
        </el-form-item>
        <el-form-item label="结果保留策略" prop="retentionPolicy">
          <el-input v-model="form.retentionPolicy" maxlength="100" placeholder="例如 30d，留空使用平台默认策略" clearable />
        </el-form-item>
        <el-form-item label="网络策略">
          <el-radio-group v-model="form.networkPolicy">
            <el-radio value="adapter_default">Adapter 默认</el-radio>
            <el-radio value="deny">禁止外部网络</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="模型白名单">
          <el-select
            v-model="form.modelAllowlist"
            multiple
            filterable
            allow-create
            default-first-option
            class="fullWidth"
            placeholder="留空表示允许 Adapter 配置的模型"
          />
          <div class="fieldHint">
            自研 Agent 填平台模型 ID；Codex / Claude 填模型名。仅影响此 Connector。
          </div>
        </el-form-item>
        <div class="policyGrid">
          <el-form-item label="单任务预算">
            <el-input-number v-model="form.maxBudgetUsd" :min="0.0001" :max="1000" :precision="4" :step="0.5" />
            <span class="unit">美元</span>
            <div class="fieldHint">SDK 支持硬预算时调用前限制；否则按回报用量做结果入库前校验。</div>
          </el-form-item>
          <el-form-item label="任务超时">
            <el-input-number v-model="form.timeoutSeconds" :min="30" :max="900" :step="30" />
            <span class="unit">秒</span>
          </el-form-item>
          <el-form-item label="最多节点">
            <el-input-number v-model="form.maxNodes" :min="5" :max="2000" :step="50" />
          </el-form-item>
          <el-form-item label="最大层级">
            <el-input-number v-model="form.maxDepth" :min="2" :max="32" />
          </el-form-item>
          <el-form-item label="并发任务数">
            <el-input-number v-model="form.maxConcurrentJobs" :min="1" :max="100" />
          </el-form-item>
        </div>
        <el-form-item label="密钥引用方式">
          <el-radio-group v-model="form.credentialMode">
            <el-radio value="keep">保持不变</el-radio>
            <el-radio value="replace">设置引用</el-radio>
            <el-radio value="clear">清除引用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.credentialMode === 'replace'" label="服务端密钥引用" prop="credentialRef">
          <el-input
            v-model="form.credentialRef"
            type="password"
            show-password
            maxlength="255"
            autocomplete="off"
            placeholder="env://变量名 或 secret://密钥路径"
          />
          <div class="fieldHint">这里只保存引用地址，真实密钥由服务端环境或密钥管理系统提供。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveConnector">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reportVisible" title="Adapter 确定性合同报告" width="680px" append-to-body>
      <template v-if="reportConnector">
        <el-alert
          v-if="reportConnector.conformanceStatus === 'stale'"
          title="Adapter 或合同版本已变化，旧检查结果已失效，请重新执行确定性检查。"
          type="warning"
          show-icon
          :closable="false"
          class="reportAlert"
        />
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Agent">{{ reportConnector.displayName }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ conformanceText(reportConnector.conformanceStatus) }}</el-descriptions-item>
          <el-descriptions-item label="合同版本">{{ reportConnector.manifest?.toolContractVersion || '-' }}</el-descriptions-item>
          <el-descriptions-item label="SMM 版本">{{ (reportConnector.manifest?.smmVersions || []).join(', ') || '-' }}</el-descriptions-item>
          <el-descriptions-item label="真实供应商执行">{{ providerExecutionText(reportConnector.conformanceReport?.providerExecution) }}</el-descriptions-item>
          <el-descriptions-item label="发布资格">{{ reportConnector.conformanceReport?.releaseEligible ? '可作为发布证据' : '不可作为发布证据' }}</el-descriptions-item>
        </el-descriptions>
        <pre class="reportJson">{{ formatReport(reportConnector.conformanceReport) }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="MindmapAiAgents">
import { computed, getCurrentInstance, onMounted, reactive, ref } from 'vue'
import {
  conformanceMindmapAiConnector,
  healthCheckMindmapAiConnector,
  listMindmapAiConnectors,
  updateMindmapAiConnector,
} from '@/api/mindmap/mindmap'

const { proxy } = getCurrentInstance()
const loading = ref(false)
const saving = ref(false)
const batchChecking = ref(false)
const connectors = ref([])
const selectedRows = ref([])
const busyKeys = reactive(new Set())
const editorVisible = ref(false)
const reportVisible = ref(false)
const editingConnector = ref(null)
const reportConnector = ref(null)
const editorRef = ref(null)
const form = reactive({
  enabled: false,
  rolloutPercentage: 100,
  dataRegion: '',
  retentionPolicy: '',
  networkPolicy: 'adapter_default',
  modelAllowlist: [],
  maxBudgetUsd: 5,
  timeoutSeconds: 900,
  maxNodes: 2000,
  maxDepth: 32,
  maxConcurrentJobs: 4,
  credentialMode: 'keep',
  credentialRef: '',
})

const rules = computed(() => ({
  credentialRef: [{
    validator: (_rule, value, callback) => {
      if (form.credentialMode !== 'replace' || /^(env|secret):\/\/.+/.test(value || '')) callback()
      else callback(new Error('请输入 env:// 或 secret:// 开头的服务端密钥引用'))
    },
    trigger: 'blur',
  }],
  retentionPolicy: [{
    validator: (_rule, value, callback) => {
      const days = Number(String(value || '').replace(/d$/, ''))
      if (!value || (/^\d+d$/.test(value) && days >= 1 && days <= 365)) callback()
      else callback(new Error('请输入 1d 到 365d，例如 30d'))
    },
    trigger: 'blur',
  }],
}))

function statusTagType(status) {
  return ({ healthy: 'success', passed: 'warning', stale: 'warning', unhealthy: 'danger', failed: 'danger' })[status] || 'info'
}

function healthText(status) {
  return ({ healthy: '健康', unhealthy: '异常', unknown: '未检查' })[status] || status || '未检查'
}

function conformanceText(status) {
  return ({ passed: '确定性检查通过', failed: '确定性检查失败', stale: '版本变化，需重检', unknown: '未检查' })[status] || status || '未检查'
}

function providerExecutionText(status) {
  return ({ completed: '已执行', partial: '部分执行', not_run: '未执行' })[status] || '未执行'
}

function displayTime(value) {
  return value ? proxy.parseTime(value) : '—'
}

function rowBusy(row, kind) {
  return busyKeys.has(`${row.agentKey}:${kind}`)
}

function replaceRow(updated) {
  const index = connectors.value.findIndex(item => item.agentKey === updated.agentKey)
  if (index >= 0) connectors.value.splice(index, 1, updated)
}

async function loadConnectors() {
  loading.value = true
  try {
    const response = await listMindmapAiConnectors()
    connectors.value = Array.isArray(response.data) ? response.data : []
  } finally {
    loading.value = false
  }
}

function openEditor(row) {
  editingConnector.value = row
  Object.assign(form, {
    enabled: row.enabled,
    rolloutPercentage: row.rolloutPercentage,
    dataRegion: row.dataRegion || '',
    retentionPolicy: row.retentionPolicy || '',
    networkPolicy: row.networkPolicy || 'adapter_default',
    modelAllowlist: [...(row.modelAllowlist || [])],
    maxBudgetUsd: row.maxBudgetUsd,
    timeoutSeconds: row.timeoutSeconds,
    maxNodes: row.maxNodes,
    maxDepth: row.maxDepth,
    maxConcurrentJobs: row.maxConcurrentJobs,
    credentialMode: 'keep',
    credentialRef: '',
  })
  editorVisible.value = true
}

async function saveConnector() {
  if (!editingConnector.value) return
  await editorRef.value?.validate()
  const payload = {
    enabled: form.enabled,
    rolloutPercentage: form.rolloutPercentage,
    dataRegion: form.dataRegion || null,
    retentionPolicy: form.retentionPolicy || null,
    networkPolicy: form.networkPolicy,
    modelAllowlist: [...form.modelAllowlist],
    maxBudgetUsd: form.maxBudgetUsd,
    timeoutSeconds: form.timeoutSeconds,
    maxNodes: form.maxNodes,
    maxDepth: form.maxDepth,
    maxConcurrentJobs: form.maxConcurrentJobs,
  }
  if (form.credentialMode === 'replace') payload.credentialRef = form.credentialRef
  if (form.credentialMode === 'clear') payload.credentialRef = ''
  saving.value = true
  try {
    const response = await updateMindmapAiConnector(editingConnector.value.agentKey, payload)
    replaceRow(response.data)
    editorVisible.value = false
    proxy.$modal.msgSuccess('Connector 配置已保存')
  } finally {
    saving.value = false
  }
}

async function runCheck(row, kind, silentSuccess = false) {
  const key = `${row.agentKey}:${kind}`
  busyKeys.add(key)
  try {
    const request = kind === 'health' ? healthCheckMindmapAiConnector : conformanceMindmapAiConnector
    const response = await request(row.agentKey)
    replaceRow(response.data)
    if (!silentSuccess) {
      const passed = kind === 'health'
        ? response.data.healthStatus === 'healthy'
        : response.data.conformanceStatus === 'passed'
      const label = kind === 'health' ? '健康检查' : '确定性合同检查'
      if (kind === 'conformance' && passed) {
        proxy.$modal.msgWarning('确定性合同检查通过；尚未执行真实供应商、安全故障注入与质量发布验收')
      } else {
        passed ? proxy.$modal.msgSuccess(`${label}通过`) : proxy.$modal.msgWarning(`${label}未通过`)
      }
    }
    return response.data
  } finally {
    busyKeys.delete(key)
  }
}

async function checkSelected() {
  batchChecking.value = true
  const targets = [...selectedRows.value]
  let passed = 0
  try {
    for (const row of targets) {
      const health = await runCheck(row, 'health', true)
      const conformance = await runCheck(health, 'conformance', true)
      if (health.healthStatus === 'healthy' && conformance.conformanceStatus === 'passed') passed += 1
    }
    const failed = targets.length - passed
    failed
      ? proxy.$modal.msgWarning(`基础检查完成：${passed} 个通过，${failed} 个需要处理；不代表发布验收`)
      : proxy.$modal.msgWarning(`基础检查完成：${passed} 个通过；仍需真实供应商、安全故障注入与质量验收`)
  } finally {
    batchChecking.value = false
  }
}

function showConformance(row) {
  reportConnector.value = row
  reportVisible.value = true
}

function formatReport(report) {
  return report ? JSON.stringify(report, null, 2) : '尚未执行一致性检查。'
}

onMounted(loadConnectors)
</script>

<style scoped lang="scss">
.agentAdminPage {
  .pageAlert { margin-bottom: 16px; }
  .agentName { font-weight: 600; margin-bottom: 4px; }
  .muted { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
  .rollout { margin-top: 4px; }
  .timeText { margin-top: 5px; white-space: nowrap; }
  .agentKeyInline { margin-left: 8px; }
  .fieldHint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.5; margin-top: 5px; }
  .fullWidth { width: 100%; }
  .policyGrid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0 16px;
  }
  .unit { margin-left: 6px; color: var(--el-text-color-secondary); font-size: 12px; }
  .reportJson {
    max-height: 360px;
    overflow: auto;
    margin: 16px 0 0;
    padding: 14px;
    border-radius: 6px;
    background: var(--el-fill-color-light);
    color: var(--el-text-color-primary);
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .reportAlert { margin-bottom: 16px; }
}
</style>
