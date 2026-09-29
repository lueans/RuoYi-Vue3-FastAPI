import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileTemplate } from '@vue/compiler-sfc'

const api = () => import('../mindmap-agent-catalog.js')
const agent = (extra = {}) => ({ agentKey: 'claude', status: 'enabled', healthStatus: 'unknown', ...extra })

test('CLI discovery is not proof of authentication or current-task readiness', async () => {
  const { agentCatalogReadiness: status } = await api()
  for (const runtime of [undefined, { status: 'detected' }, { status: 'not_installed', sdkInstalled: true }]) {
    assert.equal(status(agent({ runtime })).label, '运行前检查')
    assert.match(status(agent({ runtime })).description, /登录.*运行前/)
  }
  assert.equal(status(agent({ healthStatus: 'healthy' })).label, '环境已检查')
  assert.equal(status(agent({ healthStatus: 'healthy', agentKey: 'native_mindmap' })).label, '模型待校验')
  assert.equal(status(agent({ healthStatus: 'unexpected' })).label, '运行前检查')
})

test('selection and platform issues outrank health without granting or denying permissions', async () => {
  const { agentCatalogReadiness: status } = await api()
  const source = agent({ healthStatus: 'healthy', status: 'disabled', statusReason: '管理员未启用' })
  assert.equal(status(source).label, '暂不可用')
  assert.equal(status(source).description, '管理员未启用')
  assert.equal(status(agent(), '接口模式不匹配').description, '接口模式不匹配')
  assert.equal(status(agent(), '接口模式不匹配').label, '当前配置需处理')
  assert.equal(status(agent({ healthStatus: 'unhealthy', healthReason: '检查未通过' })).description, '检查未通过')
  assert.equal(status({}).label, '暂不可用')
  assert.equal(status(source).canSelect, undefined, 'display projection must not own authorization')
  assert.equal(source.status, 'disabled')
})

test('runtime discovery states stay separate, and absent data never becomes zero or success', async () => {
  const { agentRuntimeDiscovery: discovery } = await api()
  assert.equal(discovery(null), '尚无扫描结果')
  assert.equal(discovery({ status: 'detected' }), 'CLI 已发现')
  assert.equal(discovery({ status: 'not_installed', sdkInstalled: true }), '未发现独立 CLI · SDK 已安装')
  assert.equal(discovery({ status: 'not_installed' }), '未发现 CLI')
  assert.equal(discovery({ status: 'incompatible' }), 'CLI 协议不兼容')
  assert.equal(discovery({ status: 'probe_failed' }), 'CLI 探测失败')
  assert.equal(discovery({ status: 'future-status' }), '扫描状态未知')
  assert.equal(discovery({ status: 'constructor' }), '扫描状态未知')
})

test('scan timestamps use supplied evidence only', async () => {
  const { agentCatalogCheckTime: time } = await api()
  for (const value of [null, undefined, '', ' ', 0, -1, true, 'invalid', Infinity]) assert.equal(time(value), '')
  assert.ok(time(1790410000000))
  assert.ok(time('2026-09-26T10:30:00'))
})

test('manager labels visibility switches next to controls and renders independent readiness/discovery', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAgentManager.vue', import.meta.url), 'utf8')
  const template = parse(source).descriptor.template.content
  assert.ok((template.match(/在列表显示/g) || []).length >= 2, 'platform and device visibility labels')
  assert.ok(template.includes('agent.readiness.label'))
  assert.ok(template.includes('agentRuntimeDiscovery(agent.runtime)'))
  assert.ok(template.includes('扫描时间'))
  assert.ok(template.includes('技术信息'))
  assert.deepEqual(compileTemplate({ source: template, id: 'catalog' }).errors, [])
})

test('manager keeps closing actions visible while long catalogs scroll within the viewport', () => {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAgentManager.vue', import.meta.url), 'utf8')
  const styles = parse(source).descriptor.styles.filter(style => !style.scoped).map(style => style.content).join('\n')
  assert.ok(/\.el-dialog\.mindmapAgentManager\s*\{[^}]*max-height:\s*calc\(100dvh/.test(styles), 'bounded dialog including mobile dynamic viewport')
  assert.ok(/margin-top:[^;]+!important/.test(styles), 'override the existing global dialog margin')
  assert.ok(/\.mindmapAgentManager\s*>\s*\.el-dialog__body\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto/.test(styles), 'only the dialog body scrolls')
  assert.ok(/\.el-dialog__footer\s*\{[^}]*flex-shrink:\s*0/.test(styles), 'closing controls remain outside the scroll area')
})
