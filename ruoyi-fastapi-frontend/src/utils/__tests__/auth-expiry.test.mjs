import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  claimReloginPrompt,
  createAuthExpiredError,
  isAuthExpiredError,
  recoverExpiredBootstrap,
  releaseReloginPrompt,
} from '../auth-expiry.js'

test('401 is exposed as a structured Error with stable code and status', () => {
  const response = { status: 200, data: { code: 401 } }
  const error = createAuthExpiredError('session expired', {
    data: { reason: 'expired' },
    response,
  })

  assert.ok(error instanceof Error)
  assert.equal(error.name, 'AuthExpiredError')
  assert.equal(error.message, 'session expired')
  assert.equal(error.code, 401)
  assert.equal(error.status, 401)
  assert.deepEqual(error.data, { reason: 'expired' })
  assert.equal(error.response, response)
  assert.equal(isAuthExpiredError(error), true)
  assert.equal(isAuthExpiredError({ code: 'ERR_BAD_REQUEST', response: { status: 401 } }), true)
  assert.equal(isAuthExpiredError(new Error('offline')), false)
})

test('relogin prompt claim is single-flight until explicitly released', () => {
  const reloginState = { show: false }

  assert.equal(claimReloginPrompt(reloginState), true)
  assert.equal(claimReloginPrompt(reloginState), false)
  assert.equal(reloginState.show, true)

  releaseReloginPrompt(reloginState)
  assert.equal(reloginState.show, false)
  assert.equal(claimReloginPrompt(reloginState), true)
})

test('expired bootstrap preserves the full target and navigates once when logout rejects', async () => {
  const events = []
  const navigations = []
  const loginLocation = recoverExpiredBootstrap({
    fullPath: '/mindmap/edit?id=127&node=case-a#details',
    clearLocalAuth: () => events.push('clear-local'),
    bestEffortLogout: () => {
      events.push('remote-logout')
      return Promise.reject(new Error('logout unavailable'))
    },
    setReloginVisible: show => events.push(`relogin:${show}`),
    navigate: location => {
      events.push('navigate')
      navigations.push(location)
    },
    notify: () => events.push('notify'),
  })

  assert.deepEqual(loginLocation, {
    path: '/login',
    query: { redirect: '/mindmap/edit?id=127&node=case-a#details' },
  })
  assert.deepEqual(navigations, [loginLocation])
  assert.deepEqual(events, ['clear-local', 'relogin:false', 'navigate', 'notify'])

  await new Promise(resolve => setImmediate(resolve))
  assert.equal(navigations.length, 1)
  assert.deepEqual(events, [
    'clear-local',
    'relogin:false',
    'navigate',
    'notify',
    'remote-logout',
  ])
})

test('expired bootstrap does not wait for a logout request that never settles', async () => {
  const navigations = []
  let logoutStarted = false

  recoverExpiredBootstrap({
    fullPath: '/mindmap/edit?id=127',
    clearLocalAuth: () => undefined,
    bestEffortLogout: () => {
      logoutStarted = true
      return new Promise(() => {})
    },
    setReloginVisible: () => undefined,
    navigate: location => navigations.push(location),
  })

  assert.equal(navigations.length, 1)
  assert.deepEqual(navigations[0], {
    path: '/login',
    query: { redirect: '/mindmap/edit?id=127' },
  })
  await Promise.resolve()
  assert.equal(logoutStarted, true)
  assert.equal(navigations.length, 1)
})

test('request, guard, store and logout API wire the expiry contract together', async () => {
  const [requestSource, permissionSource, userStoreSource, loginApiSource] = await Promise.all([
    readFile(new URL('../request.js', import.meta.url), 'utf8'),
    readFile(new URL('../../permission.js', import.meta.url), 'utf8'),
    readFile(new URL('../../store/modules/user.js', import.meta.url), 'utf8'),
    readFile(new URL('../../api/login.js', import.meta.url), 'utf8'),
  ])

  assert.match(requestSource, /return Promise\.reject\(createAuthExpiredError\(/)
  assert.match(requestSource, /claimReloginPrompt\(isRelogin\)/)
  assert.match(permissionSource, /isAuthExpiredError\(err\)[\s\S]*?fullPath: to\.fullPath/)
  assert.match(permissionSource, /navigate: loginLocation => next\(loginLocation\)/)
  assert.match(userStoreSource, /resetToken\(\)[\s\S]*?removeToken\(\)/)
  assert.match(userStoreSource, /logOutRemote\(token = this\.token\)[\s\S]*?return logout\(token\)/)
  assert.match(loginApiSource, /headers = \{ isToken: false \}[\s\S]*?url: '\/logout'[\s\S]*?skipAuthExpiredHandler: true/)
})
