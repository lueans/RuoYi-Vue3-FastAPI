import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import axios from 'axios'
import { createRenderer, reactive } from 'vue'
import * as expiry from '../auth-expiry.js'
import { getCurrentLoginReturnPath } from '../login-redirect.js'
import { useMindmapAuthExpiry } from '../use-mindmap-auth-expiry.js'

const requestSource = await readFile(new URL('../request.js', import.meta.url), 'utf8')
const authSource = await readFile(new URL('../auth.js', import.meta.url), 'utf8')
const stripImports = source => source.replace(/^import[\s\S]*?from\s+['"][^'"]+['"];?\s*$/gm, '')
const tick = () => new Promise(resolve => setImmediate(resolve))
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

// Execute the actual interceptor module with real Axios and an in-memory
// transport. Only host integrations (cookies, UI and encryption) are replaced.
function harness(t, { encrypt = async config => config } = {}) {
  expiry.resetAuthExpirySession()
  t.after(() => expiry.resetAuthExpirySession())
  let token = 'session-a'
  const prompts = [], messages = [], requests = [], logouts = []
  const location = { pathname: '/mindmap/edit', search: '?id=130', hash: '#node', href: '' }
  const user = reactive({
    id: 42, token: 'session-a', roles: ['editor'],
    resetToken() { token = ''; this.token = ''; this.roles = [] },
    logOutRemote(value) { logouts.push(value); return Promise.reject(new Error('offline')) },
  })
  const ElMessage = options => messages.push(options)
  ElMessage.error = message => messages.push(message)
  const dependencies = {
    axios,
    ElNotification: { error: message => messages.push(message) },
    ElMessageBox: { confirm() { const prompt = deferred(); prompts.push(prompt); return prompt.promise } },
    ElMessage, ElLoading: {}, getToken: () => token,
    errorCode: { 401: 'expired', default: 'error' },
    tansParams: value => new URLSearchParams(value).toString(), blobValidate: () => true,
    cache: { session: { getJSON() {}, setJSON() {} } }, saveAs() {}, useUserStore: () => user,
    decryptTransportErrorResponse: async error => error,
    decryptTransportResponse: async response => response,
    encryptTransportRequest: encrypt,
    invalidateTransportKeyMeta() {}, resetTransportRequestConfig() {},
    shouldRetryTransportWithFreshKey: () => false,
    createRepeatSubmitRecord: async () => null, isDuplicateRepeatSubmit: () => false,
    isRepeatSubmitMethod: () => false,
    getCurrentLoginReturnPath, ...expiry, location,
    console: { log() {}, warn() {}, error() {} },
  }
  const source = stripImports(requestSource)
    .replaceAll('import.meta.env.VITE_APP_BASE_API', "'/api'")
    .replace(/export (?=(?:let|const|function|async function)\b)/g, '')
    .replace('export default service', 'return { service, requestAuthLogin, isRelogin }')
  const runtime = new Function(...Object.keys(dependencies), source)(...Object.values(dependencies))
  let respond = config => ({ status: 200, data: { code: 200 }, config, headers: {}, request: {} })
  runtime.service.defaults.adapter = async config => { requests.push(config); return respond(config) }
  const cookieApi = { get: () => token, set(_name, value) { token = value; return value }, remove() { token = '' } }
  const auth = new Function('Cookies', 'resetAuthExpirySession',
    stripImports(authSource).replace(/export /g, '') + '\nreturn { setToken, getToken }',
  )(cookieApi, expiry.resetAuthExpirySession)
  return {
    ...runtime, auth, user, prompts, messages, requests, logouts, location,
    get token() { return token },
    externalLogin(value) { token = value },
    respond(fn) { respond = fn },
    subscribe(handler) { const unsubscribe = expiry.subscribeAuthExpiry(handler); t.after(unsubscribe); return unsubscribe },
  }
}

const response = (config, code = 401) => ({ status: 200, data: { code, msg: 'expired' }, config, headers: {}, request: {} })
const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
})
function mountAuthPanel(t, h, onExpired) {
  let expired
  const app = renderer.createApp({ setup() {
    expired = useMindmapAuthExpiry(() => h.user.token, onExpired)
    return () => null
  } })
  app.mount({})
  t.after(() => app.unmount())
  return expired
}

test('dismissed expiry stays latched: later authenticated requests never reach Axios transport or reopen the prompt', async t => {
  const h = harness(t)
  const events = []
  h.subscribe(event => events.push(event))
  h.respond(config => response(config))
  await assert.rejects(h.service.get('/mindmap/130', { silentError: true }), expiry.isAuthExpiredError)
  assert.equal(h.prompts.length, 1)
  assert.equal(h.token, 'session-a')
  assert.equal(h.user.id, 42)
  assert.deepEqual(events, [{ kind: 'expired' }])
  h.prompts[0].reject('cancel')
  await tick()
  for (let attempt = 0; attempt < 3; attempt++) {
    await assert.rejects(h.service.get('/mindmap/ai/jobs/current', { silentError: true }), expiry.isAuthExpiredError)
  }
  assert.equal(h.requests.length, 1)
  assert.equal(h.prompts.length, 1)
  assert.equal(h.messages.length, 0)
})

test('late business and HTTP 401s from an old credential cannot expire a newly logged-in session', async t => {
  for (const httpError of [false, true]) {
    const h = harness(t)
    const pending = deferred()
    h.respond(() => pending.promise)
    const request = h.service.get('/mindmap/130')
    const rejected = assert.rejects(request, expiry.isAuthExpiredError)
    await tick()
    const oldConfig = h.requests[0]
    h.auth.setToken('session-b')
    h.user.token = 'session-b'
    if (httpError) {
      pending.reject(new axios.AxiosError('unauthorized', 'ERR_BAD_REQUEST', oldConfig, {}, {
        ...response(oldConfig), status: 401,
      }))
    } else pending.resolve(response(oldConfig))
    await rejected
    assert.equal(h.prompts.length, 0)
    assert.equal(expiry.isAuthSessionExpired('session-b'), false)
    assert.equal(h.token, 'session-b')
  }
})

test('cookie disappearance protects the mounted owner before transport and fences later requests', async t => {
  const h = harness(t)
  let cleanupCalls = 0
  h.subscribe(() => {
    assert.equal(expiry.isAuthSessionExpired(h.user.token), true)
    cleanupCalls++
  })
  h.externalLogin(undefined)
  h.respond(config => {
    assert.equal(config.headers.Authorization, undefined, 'removed credentials must not be reused')
    assert.fail('a missing-cookie request must not reach transport')
  })
  await assert.rejects(h.service.get('/mindmap/130', { silentError: true }), error => (
    expiry.isAuthExpiredError(error) && error.authSessionChanged === true
  ))
  assert.equal(h.user.token, 'session-a', 'keep draft ownership until cleanup finishes')
  assert.equal(cleanupCalls, 1)
  assert.equal(h.prompts.length, 1)
  h.prompts[0].reject('cancel')
  await tick()
  for (let attempt = 0; attempt < 3; attempt++) {
    await assert.rejects(h.service.get('/mindmap/ai/jobs/current'), expiry.isAuthExpiredError)
  }
  assert.equal(h.requests.length, 0, 'removed credentials must be fenced before transport')
  assert.equal(h.prompts.length, 1)
  assert.equal(cleanupCalls, 1)
  assert.equal(h.messages.length, 0)
})

test('missing-cookie relogin confirmation and inline action wait for the same draft cleanup', async t => {
  const h = harness(t)
  const backup = deferred()
  h.subscribe(() => backup.promise)
  h.externalLogin(undefined)
  h.respond(config => response(config))
  await assert.rejects(h.service.get('/mindmap/130'), expiry.isAuthExpiredError)
  h.prompts[0].resolve('confirm')
  await tick()
  const login = h.requestAuthLogin()
  assert.equal(h.requestAuthLogin(), login)
  assert.equal(h.location.href, '')
  assert.equal(h.user.token, 'session-a')
  backup.resolve()
  assert.equal(await login, true)
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
  assert.equal(h.token, undefined)
  assert.deepEqual(h.logouts, [], 'do not reissue logout for an already removed cookie')
})

test('removing a cookie while its request is in flight still expires the matching mounted owner', async t => {
  const h = harness(t)
  const pending = deferred()
  let cleaned = false
  h.subscribe(() => { cleaned = true })
  h.respond(() => pending.promise)
  const request = h.service.get('/mindmap/130')
  const rejected = assert.rejects(request, expiry.isAuthExpiredError)
  await tick()
  assert.equal(h.requests[0].headers.Authorization, 'Bearer session-a')
  h.externalLogin(undefined)
  pending.resolve(response(h.requests[0]))
  await rejected
  assert.equal(expiry.isAuthSessionExpired(h.user.token), true)
  assert.equal(cleaned, true)
  assert.equal(h.prompts.length, 1)
})

test('a new cookie login survives a missing-cookie confirmation already waiting for draft cleanup', async t => {
  const h = harness(t)
  const backup = deferred()
  h.subscribe(() => backup.promise)
  h.externalLogin(undefined)
  h.respond(config => response(config))
  await assert.rejects(h.service.get('/mindmap/130'), expiry.isAuthExpiredError)
  const login = h.requestAuthLogin()
  h.externalLogin('session-b')
  backup.resolve()
  assert.equal(await login, false)
  assert.equal(h.token, 'session-b')
  assert.equal(h.location.href, '')
  assert.deepEqual(h.logouts, [])
})

test('credential-free late 401 cannot pause a newer cookie or a new mounted owner', async t => {
  for (const newCookie of ['session-b', undefined]) {
    const h = harness(t)
    const pending = deferred()
    h.user.token = ''
    h.externalLogin(undefined)
    h.respond(() => pending.promise)
    const request = h.service.get('/mindmap/130')
    const rejected = assert.rejects(request, expiry.isAuthExpiredError)
    await tick()
    assert.equal(h.requests.length, 1, 'the request starts without a cookie or mounted owner')
    assert.equal(h.requests[0].headers.Authorization, undefined)
    h.user.token = 'session-b'
    h.externalLogin(newCookie)
    pending.resolve(response(h.requests[0]))
    await rejected
    assert.equal(h.prompts.length, 0)
    assert.equal(expiry.hasAuthExpiredSession(), false)
    assert.equal(h.user.token, 'session-b')
  }
})

test('explicit anonymous requests and a genuinely logged-out page do not expire a mounted session', async t => {
  const h = harness(t)
  h.externalLogin(undefined)
  h.respond(config => response(config))
  await assert.rejects(h.service.post('/login', {}, { headers: { isToken: false } }), expiry.isAuthExpiredError)
  await assert.rejects(h.service.get('/public/view/token', { headers: { isToken: false } }), expiry.isAuthExpiredError)
  assert.equal(expiry.hasAuthExpiredSession(), false)
  h.user.token = ''
  await assert.rejects(h.service.get('/mindmap/130'), expiry.isAuthExpiredError)
  assert.equal(h.prompts.length, 0)
  assert.equal(expiry.hasAuthExpiredSession(), false)
})

test('a cross-tab cookie change pauses the old Vue owner and protects its drafts without rejecting the new cookie', async t => {
  const h = harness(t)
  const backup = deferred()
  const draftOwners = []
  const expired = mountAuthPanel(t, h, () => {
    draftOwners.push({ id: h.user.id, token: h.user.token })
    return backup.promise
  })
  h.externalLogin('session-b')
  h.respond(() => assert.fail('an old-owner request must not reach transport with the replacement cookie'))
  await assert.rejects(h.service.get('/mindmap/130', { silentError: true }), error => (
    expiry.isAuthExpiredError(error) && error.authSessionChanged === true
  ))
  assert.equal(expired.value, true)
  assert.equal(expiry.isAuthSessionExpired('session-a'), true)
  assert.equal(expiry.isAuthSessionExpired('session-b'), false)
  assert.deepEqual(draftOwners, [{ id: 42, token: 'session-a' }])
  h.prompts[0].resolve('confirm')
  await tick()
  assert.equal(h.location.href, '')
  assert.equal(h.user.token, 'session-a')
  await assert.rejects(h.service.post('/mindmap/130/changes', { text: 'old-owner draft' }), expiry.isAuthExpiredError)
  assert.equal(h.requests.length, 0, 'old-owner drafts must not be sent using the replacement cookie')
  const login = h.requestAuthLogin()
  backup.resolve()
  assert.equal(await login, true)
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
  assert.equal(h.token, 'session-b', 'reloading the old page must preserve the replacement cookie')
  assert.deepEqual(h.logouts, [])
})

test('an old Vue owner stays fenced after another fresh cookie arrives without expiring that new credential', async t => {
  const h = harness(t)
  const backup = deferred()
  let cleanupCalls = 0
  const expired = mountAuthPanel(t, h, () => { cleanupCalls++; return backup.promise })
  h.externalLogin('session-b')
  h.respond(config => response(config))
  await assert.rejects(h.service.get('/mindmap/130'), error => (
    expiry.isAuthExpiredError(error) && error.authSessionChanged === true
  ))
  h.externalLogin('session-c')
  await assert.rejects(h.service.post('/mindmap/130/changes', { text: 'old-owner draft' }), expiry.isAuthExpiredError)
  assert.equal(h.requests.length, 0)
  assert.equal(expired.value, true)
  assert.equal(cleanupCalls, 1)
  assert.equal(expiry.isAuthSessionExpired('session-c'), false, 'a local fence is not a server rejection')
  assert.equal(h.prompts.length, 1)
  const login = h.requestAuthLogin()
  await tick()
  assert.equal(h.location.href, '')
  backup.resolve()
  assert.equal(await login, true)
  assert.equal(h.token, 'session-c')
  assert.deepEqual(h.logouts, [])
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
})

test('an in-flight 401 after a cross-tab switch cannot pause a newly logged-in Vue owner', async t => {
  const h = harness(t)
  const pending = deferred()
  let cleanupCalls = 0
  const expired = mountAuthPanel(t, h, () => { cleanupCalls++ })
  h.respond(() => pending.promise)
  const request = h.service.get('/mindmap/130')
  const rejected = assert.rejects(request, expiry.isAuthExpiredError)
  await tick()
  const oldConfig = h.requests[0]
  assert.equal(h.requests.length, 1)
  assert.equal(oldConfig.headers.Authorization, 'Bearer session-a')
  h.externalLogin('session-b')
  h.auth.setToken('session-c')
  h.user.token = 'session-c'
  pending.resolve(response(oldConfig))
  await rejected
  assert.equal(expired.value, false)
  assert.equal(cleanupCalls, 0)
  assert.equal(expiry.hasAuthExpiredSession(), false)
  assert.equal(h.prompts.length, 0)
  assert.equal(h.token, 'session-c')
  assert.deepEqual(h.logouts, [])
})

test('login, anonymous reads and explicit logout bypass expiry, and actual setToken resets the latch', async t => {
  const h = harness(t)
  expiry.markAuthSessionExpired(h.token)
  h.respond(config => response(config, 200))
  await h.service.post('/login', {}, { headers: { isToken: false } })
  await h.service.get('/public/view/token', { headers: { isToken: false } })
  await h.service.post('/logout', {}, {
    headers: { isToken: false, Authorization: 'Bearer session-a' }, skipAuthExpiredHandler: true,
  })
  assert.equal(h.requests.length, 3)
  assert.equal(h.prompts.length, 0)
  h.auth.setToken('session-b')
  h.user.token = 'session-b'
  assert.equal(expiry.isAuthSessionExpired('session-a'), false)
  await h.service.get('/mindmap/130')
  assert.equal(h.requests[3].headers.Authorization, 'Bearer session-b')
  h.respond(config => response(config))
  await assert.rejects(h.service.post('/login', {}, { headers: { isToken: false } }), expiry.isAuthExpiredError)
  assert.equal(expiry.isAuthSessionExpired('session-b'), false)
  assert.equal(h.prompts.length, 0)
})

test('relogin confirmation waits for draft cleanup, coalesces explicit clicks and preserves the full return path', async t => {
  const h = harness(t)
  const backup = deferred()
  h.subscribe(() => backup.promise)
  h.respond(config => response(config))
  await assert.rejects(h.service.get('/mindmap/130'))
  h.prompts[0].resolve('confirm')
  await tick()
  const login = h.requestAuthLogin()
  assert.equal(h.requestAuthLogin(), login)
  assert.equal(h.token, 'session-a')
  assert.equal(h.location.href, '')
  backup.resolve()
  assert.equal(await login, true)
  await tick()
  assert.equal(h.token, '')
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
  assert.deepEqual(h.logouts, ['session-a'])
})

test('failed backup blocks navigation; explicit retry reruns only failed cleanup and reports once per action', async t => {
  const h = harness(t)
  let failing = true, failedCalls = 0, successfulCalls = 0
  h.subscribe(() => { successfulCalls++ })
  h.subscribe(() => { failedCalls++; if (failing) return Promise.reject(new Error('draft unavailable')) })
  expiry.markAuthSessionExpired(h.token)
  await tick()
  await assert.rejects(expiry.waitForAuthExpiryCleanup(), /draft unavailable/)
  assert.equal(await h.requestAuthLogin(), false)
  assert.equal(h.messages.length, 1)
  assert.equal(h.token, 'session-a')
  assert.equal(h.location.href, '')
  failing = false
  assert.equal(await h.requestAuthLogin(), true)
  assert.equal(failedCalls, 3)
  assert.equal(successfulCalls, 1)
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
})

test('a newer login survives an old relogin confirmation waiting on backup', async t => {
  const h = harness(t)
  const backup = deferred()
  h.subscribe(() => backup.promise)
  expiry.markAuthSessionExpired(h.token)
  const login = h.requestAuthLogin()
  h.auth.setToken('session-b')
  h.user.token = 'session-b'
  backup.resolve()
  assert.equal(await login, false)
  assert.equal(h.token, 'session-b')
  assert.equal(h.location.href, '')
  assert.deepEqual(h.logouts, [])
})

test('inline relogin remounts a newer cookie session from another tab without clearing it', async t => {
  const h = harness(t)
  const backup = deferred()
  h.subscribe(() => backup.promise)
  expiry.markAuthSessionExpired(h.token)
  h.externalLogin('session-from-another-tab')
  const login = h.requestAuthLogin()
  await tick()
  assert.equal(h.location.href, '')
  backup.resolve()
  assert.equal(await login, true)
  assert.equal(h.token, 'session-from-another-tab')
  assert.deepEqual(h.logouts, [])
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
})

test('inline relogin still protects drafts and reaches login after another tab removes the cookie', async t => {
  const h = harness(t)
  const backup = deferred()
  h.subscribe(() => backup.promise)
  expiry.markAuthSessionExpired(h.token)
  h.externalLogin(undefined)
  const login = h.requestAuthLogin()
  await tick()
  assert.equal(h.location.href, '')
  backup.resolve()
  assert.equal(await login, true)
  assert.equal(h.token, undefined)
  assert.deepEqual(h.logouts, [])
  assert.equal(h.location.href, '/mindmap/edit?id=130#node')
})

test('cross-tab cookie changes do not hide failed backup feedback or permit navigation', async t => {
  for (const externalToken of [undefined, 'new-session']) {
    const h = harness(t)
    h.subscribe(() => Promise.reject(new Error('draft unavailable')))
    expiry.markAuthSessionExpired(h.token)
    h.externalLogin(externalToken)
    await tick()
    assert.equal(await h.requestAuthLogin(), false)
    assert.equal(h.messages.length, 1)
    assert.equal(h.location.href, '')
    assert.equal(h.token, externalToken)
    assert.deepEqual(h.logouts, [])
  }
})

test('expiry while request encryption is pending fences the adapter and immediately informs late subscribers', async t => {
  const encryption = deferred()
  const h = harness(t, { encrypt: async config => { await encryption.promise; return config } })
  const request = h.service.get('/mindmap/130')
  const rejected = assert.rejects(request, expiry.isAuthExpiredError)
  await tick()
  expiry.markAuthSessionExpired(h.token)
  let notified = false
  h.subscribe(event => { notified = event.kind === 'expired'; assert.equal(Object.hasOwn(event, 'token'), false) })
  assert.equal(notified, true)
  encryption.resolve()
  await rejected
  assert.equal(h.requests.length, 0)
})
