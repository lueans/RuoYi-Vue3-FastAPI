import axios from 'axios'
import { ElNotification , ElMessageBox, ElMessage, ElLoading } from 'element-plus'
import { getToken } from '@/utils/auth'
import errorCode from '@/utils/errorCode'
import { tansParams, blobValidate } from '@/utils/ruoyi'
import cache from '@/plugins/cache'
import { saveAs } from 'file-saver'
import useUserStore from '@/store/modules/user'
import {
  decryptTransportErrorResponse,
  decryptTransportResponse,
  encryptTransportRequest,
  invalidateTransportKeyMeta,
  resetTransportRequestConfig,
  shouldRetryTransportWithFreshKey
} from '@/utils/transportCrypto'
import {
  createRepeatSubmitRecord,
  isDuplicateRepeatSubmit,
  isRepeatSubmitMethod
} from '@/utils/requestDedupe'
import { getCurrentLoginReturnPath } from '@/utils/login-redirect'
import {
  claimReloginPrompt,
  claimAuthExpiryPrompt,
  createAuthExpiredError,
  isAuthExpiredError,
  isAuthSessionExpired,
  hasAuthExpiredSession,
  markAuthSessionExpired,
  waitForAuthExpiryCleanup,
  releaseReloginPrompt
} from '@/utils/auth-expiry'

let downloadLoadingInstance;
// 是否显示重新登录
export let isRelogin = { show: false };
let activeAuthPromptToken = null
let authLoginAttempt = null

function shouldHandleAuthExpired(config) {
  return config?.skipAuthExpiredHandler !== true
}

function assertAuthSessionUsable(config) {
  if ((isAuthSessionExpired(config?.__authSessionToken)
      || isAuthSessionExpired(config?.__authSessionOwnerToken))
    && shouldHandleAuthExpired(config)) {
    const error = createAuthExpiredError('登录状态已失效，请重新登录后继续')
    error.config = config
    // This is a local owner fence, not a 401 proving a newly replaced cookie
    // invalid. The response interceptor must not revoke that newer credential.
    error.authExpiryHandled = true
    throw error
  }
}

async function loginAfterExpiredSession(expiredToken) {
  if (getToken() !== expiredToken || !hasAuthExpiredSession()) return false
  const newSessionInAnotherTab = !isAuthSessionExpired(expiredToken)
  const returnPath = getCurrentLoginReturnPath(location)
  try {
    await waitForAuthExpiryCleanup({ retryFailed: true })
  } catch {
    if (getToken() === expiredToken && hasAuthExpiredSession()) {
      ElMessage.error('未能安全保存当前编辑内容，请先重试保存或备份，再重新登录')
    }
    return false
  }
  // A newer login (including another tab) must survive an old dialog's click
  // or a late draft-cleanup completion.
  if (getToken() !== expiredToken || !hasAuthExpiredSession()) return false
  if (newSessionInAnotherTab) {
    // Another tab can replace or remove the cookie without updating this
    // tab's Pinia identity. After protecting the old editor, remount with the
    // current cookie (or let the route guard open login if it was removed).
    // Never clear or log out a newer credential.
    location.href = returnPath
    return true
  }
  if (!isAuthSessionExpired(expiredToken)) return false
  const userStore = useUserStore()
  userStore.resetToken()
  // Local revocation and navigation do not depend on the logout endpoint.
  location.href = returnPath
  Promise.resolve()
    .then(() => userStore.logOutRemote(expiredToken))
    .catch(() => undefined)
  return true
}

function requestAuthLoginForToken(token) {
  if (authLoginAttempt && authLoginAttempt.token === token) return authLoginAttempt.promise
  const attempt = { token, promise: null }
  authLoginAttempt = attempt
  attempt.promise = loginAfterExpiredSession(token).finally(() => {
    if (authLoginAttempt === attempt) authLoginAttempt = null
  })
  return attempt.promise
}

// Inline “重新登录” actions reuse the protected exit without reopening a
// dismissed modal. Failed draft protection can be retried explicitly.
export function requestAuthLogin() {
  return requestAuthLoginForToken(getToken())
}
export const requestRelogin = requestAuthLogin

function handleAuthExpired(config) {
  const token = config?.__authSessionToken
  if (!shouldHandleAuthExpired(config) || !token) return
  const cookieToken = getToken()
  const ownerToken = useUserStore().token
  // Another tab can remove the cookie while this tab still owns an editor and
  // unsaved input. Expire that captured owner, but never a newer cookie/login.
  const currentSessionToken = cookieToken || ownerToken
  if (token !== currentSessionToken) return
  markAuthSessionExpired(token, {
    // A still-mounted editor retains its original owner when another tab logs
    // in. Protect its local drafts too, without assigning them to the cookie's
    // user. A request from an older mounted owner cannot terminate a new one.
    ownerToken: config.__authSessionOwnerToken === ownerToken ? ownerToken : null,
  })
  // The bootstrap route guard temporarily owns the legacy prompt gate.
  if (isRelogin.show && !activeAuthPromptToken) return
  if (!claimAuthExpiryPrompt(token)) return
  if (!isRelogin.show) claimReloginPrompt(isRelogin)
  activeAuthPromptToken = token
  ElMessageBox.confirm(
    '登录状态已过期，您可以继续留在该页面，或者重新登录',
    '系统提示',
    { confirmButtonText: '重新登录', cancelButtonText: '取消', type: 'warning' },
  ).then(() => requestAuthLoginForToken(cookieToken)).catch(() => undefined).finally(() => {
    if (activeAuthPromptToken === token) {
      activeAuthPromptToken = null
      releaseReloginPrompt(isRelogin)
    }
  })
}

axios.defaults.headers['Content-Type'] = 'application/json;charset=utf-8'
// 创建axios实例
const service = axios.create({
  // axios中请求配置有baseURL选项，表示请求URL公共部分
  baseURL: import.meta.env.VITE_APP_BASE_API,
  // 超时
  timeout: 10000
})

/**
 * 统一处理请求发送前的公共逻辑。
 *
 * @param {Object} config Axios 请求配置
 * @returns {Promise<Object>} 最终发送的请求配置
 */
// request拦截器
service.interceptors.request.use(async config => {
  // 是否需要设置 token
  const isToken = (config.headers || {}).isToken === false
  // 是否需要防止数据重复提交
  const isRepeatSubmit = (config.headers || {}).repeatSubmit === false
  // 间隔时间(ms)，小于此时间视为重复提交
  const interval = (config.headers || {}).interval || 1000
  const token = !isToken ? getToken() : null
  const ownerToken = isToken ? null : useUserStore().token || null
  // Keep the mounted session's identity if its cookie disappeared. This is
  // only an expiry/cleanup fence: never reuse the removed token as a credential.
  // Explicitly anonymous requests (login, public shares, logout) stay exempt.
  config.__authSessionOwnerToken = ownerToken
  config.__authSessionToken = token || ownerToken
  assertAuthSessionUsable(config)
  if (token) {
    config.headers['Authorization'] = 'Bearer ' + token // 让每个请求携带自定义token 请根据实际情况自行修改
  }
  if (!isRepeatSubmit && isRepeatSubmitMethod(config.method)) {
    try {
      const requestRecord = await createRepeatSubmitRecord(config)
      if (requestRecord) {
        const sessionRecord = cache.session.getJSON('sessionObj')
        if (isDuplicateRepeatSubmit(sessionRecord, requestRecord, interval)) {
          const message = '数据正在处理，请勿重复提交'
          console.warn(`[${requestRecord.url}]: ${message}`)
          return Promise.reject(new Error(message))
        }
        cache.session.setJSON('sessionObj', requestRecord)
      }
    } catch (error) {
      // 指纹或浏览器存储不可用时只降级防重能力，不得跳过后续传输加密与请求发送。
      console.warn(`[${config.url}]: 无法进行防重复提交验证。`, error)
    }
  }
  // 在参数拼接前完成传输层加密，避免明文查询串提前写入 URL。
  config = await encryptTransportRequest(config)
  // Another response may expire the session while encryption/key discovery
  // was pending. Fence again before Axios reaches its transport adapter.
  assertAuthSessionUsable(config)
  // get请求映射params参数
  if (config.method === 'get' && config.params) {
    let url = config.url + '?' + tansParams(config.params);
    url = url.slice(0, -1);
    config.params = {};
    config.url = url;
  }
  return config
}, error => {
    console.log(error)
    return Promise.reject(error)
})

/**
 * 统一处理响应成功场景下的解密与业务状态码判断。
 *
 * @param {Object} res Axios 响应对象
 * @returns {Promise<Object>} 业务响应数据
 */
// 响应拦截器
service.interceptors.response.use(async res => {
    // 响应若命中了传输层加密，这里先还原为原始业务 JSON。
    res = await decryptTransportResponse(res)
    // 未设置状态码则默认成功状态
    const code = Number(res.data.code ?? 200);
    const silentError = res.config?.silentError === true
    // 获取错误信息
    const msg = errorCode[code] || res.data.msg || errorCode['default']
    // 二进制数据则直接返回
    if (res.request.responseType ===  'blob' || res.request.responseType ===  'arraybuffer') {
      return res.data
    }
    if (code === 401) {
      handleAuthExpired(res.config)
      return Promise.reject(createAuthExpiredError(
        res.data.msg || msg,
        { data: res.data.data, response: res },
      ))
    } else if (code === 500) {
      if (!silentError) ElMessage({ message: msg, type: 'error' })
      const businessError = new Error(msg)
      businessError.data = res.data.data
      businessError.code = code
      return Promise.reject(businessError)
    } else if (code === 601) {
      if (!silentError) ElMessage({ message: msg, type: 'warning' })
      const businessError = new Error(msg)
      businessError.data = res.data.data
      businessError.code = code
      return Promise.reject(businessError)
    } else if (code !== 200) {
      if (!silentError) ElNotification.error({ title: msg })
      return Promise.reject('error')
    } else {
      return  Promise.resolve(res.data)
    }
  },
  async error => {
    // 主动取消属于调用方生命周期控制，不是网络或业务错误。直接透传，避免
    // 快速切换页面、文件或搜索条件时弹出误导性的 “canceled” 错误消息。
    if (axios.isCancel(error) || error?.code === 'ERR_CANCELED') {
      return Promise.reject(error)
    }
    // 错误响应也可能是加密信封，先尝试解密再进入统一错误提示流程。
    error = await decryptTransportErrorResponse(error)
    // 若后端提示密钥失效，则清空本地公钥缓存并基于原始请求重试一次。
    if (shouldRetryTransportWithFreshKey(error) && error.config && !error.config.__transportRetried) {
      invalidateTransportKeyMeta()
      error.config.__transportRetried = true
      error.config.headers = error.config.headers || {}
      error.config.headers.repeatSubmit = false
      resetTransportRequestConfig(error.config)
      return service.request(error.config)
    }
    console.log('err' + error)
    const response = error.response
    const responseStatus = response?.status
    const responseCode = response?.data?.code
    const responseMsg = response?.data?.msg
    const authExpired = isAuthExpiredError(error)
    if (authExpired) {
      const skipAuthExpiredHandler = (
        !shouldHandleAuthExpired(error.config)
        || !shouldHandleAuthExpired(response?.config)
      )
      if (!skipAuthExpiredHandler && error.authExpiryHandled !== true) {
        handleAuthExpired(error.config || response?.config)
      }
      return Promise.reject(createAuthExpiredError(
        responseMsg || errorCode[401],
        { data: response?.data?.data, response },
      ))
    }
    // 后台轮询可自行聚合普通错误，但认证失效必须继续进入全局可见处理，
    // 不能因为调用方要求静默而让用户停留在已经失效的会话中。
    const silentError = (
      error.config?.silentError === true
      || response?.config?.silentError === true
    ) && responseStatus !== 401 && responseCode !== 401
    if (responseMsg) {
      const messageType = responseStatus === 429 || responseCode === 429 ? 'warning' : 'error'
      if (!silentError) ElMessage({ message: responseMsg, type: messageType, duration: 5 * 1000 })
      // 保留 HTTP 响应元数据，供静默恢复流程区分“资源确实不存在”和
      // 临时网络/服务故障；只抛裸 Error 会让调用方无法安全决定是否重试。
      const responseError = new Error(responseMsg)
      responseError.response = response
      responseError.status = responseStatus
      responseError.code = responseCode ?? responseStatus
      return Promise.reject(responseError)
    }
    let { message } = error;
    if (message == "Network Error") {
      message = "后端接口连接异常";
    } else if (message.includes("timeout")) {
      message = "系统接口请求超时";
    } else if (message.includes("Request failed with status code")) {
      message = "系统接口" + message.slice(-3) + "异常";
    }
    if (!silentError) ElMessage({ message: message, type: 'error', duration: 5 * 1000 })
    return Promise.reject(error)
  }
)

/**
 * 通用文件下载方法。
 *
 * @param {string} url 下载接口地址
 * @param {*} params 请求参数
 * @param {string} filename 下载文件名
 * @param {Object} config 额外请求配置
 * @returns {Promise<void>}
 */
// 通用下载方法
export function download(url, params, filename, config) {
  downloadLoadingInstance = ElLoading.service({ text: "正在下载数据，请稍候", background: "rgba(0, 0, 0, 0.7)", })
  return service.post(url, params, {
    transformRequest: [(params) => { return tansParams(params) }],
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', encrypt: false, encryptResponse: false },
    responseType: 'blob',
    ...config
  }).then(async (data) => {
    const isBlob = blobValidate(data);
    if (isBlob) {
      const blob = new Blob([data])
      saveAs(blob, filename)
    } else {
      const resText = await data.text();
      const rspObj = JSON.parse(resText);
      const errMsg = errorCode[rspObj.code] || rspObj.msg || errorCode['default']
      ElMessage.error(errMsg);
    }
    downloadLoadingInstance.close();
  }).catch((r) => {
    console.error(r)
    ElMessage.error('下载文件出现错误，请联系管理员！')
    downloadLoadingInstance.close();
  })
}

export default service
