import request from '@/utils/request'

// 登录方法
export function login(username, password, code, uuid) {
  const data = {
    username,
    password,
    code,
    uuid
  }
  return request({
    url: '/login',
    headers: {
      isToken: false,
      repeatSubmit: false,
      'Content-Type': 'application/x-www-form-urlencoded'
    },
    method: 'post',
    data: data
  })
}

// 注册方法
export function register(data) {
  return request({
    url: '/register',
    headers: {
      isToken: false
    },
    method: 'post',
    data: data
  })
}

// 获取用户详细信息
export function getInfo() {
  return request({
    url: '/getInfo',
    method: 'get'
  })
}

// 退出方法
export function logout(token) {
  const headers = { isToken: false }
  if (token) headers.Authorization = `Bearer ${token}`
  return request({
    url: '/logout',
    method: 'post',
    // 固定使用调用时捕获的旧 token，避免迟到的注销请求误带新会话 token。
    headers,
    // logout 本身若返回 401，只向调用方返回结构化错误；不能再次触发
    // 全局重新登录弹窗，否则会形成 logout -> 401 -> logout 的递归链路。
    skipAuthExpiredHandler: true
  })
}

// 获取验证码
export function getCodeImg() {
  return request({
    url: '/captchaImage',
    headers: {
      isToken: false
    },
    method: 'get',
    timeout: 20000
  })
}

export function feishuAuthorize() {
  return request({
    url: '/feishu/authorize',
    headers: {
      isToken: false
    },
    method: 'get'
  })
}

export function feishuLogin(code) {
  return request({
    url: '/feishu/login',
    headers: {
      isToken: false
    },
    method: 'post',
    data: { code }
  })
}
