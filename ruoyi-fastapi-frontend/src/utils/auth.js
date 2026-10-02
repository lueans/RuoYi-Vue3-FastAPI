import Cookies from 'js-cookie'
import { resetAuthExpirySession } from './auth-expiry.js'

const TokenKey = 'Admin-Token'

export function getToken() {
  return Cookies.get(TokenKey)
}

export function setToken(token) {
  const result = Cookies.set(TokenKey, token)
  resetAuthExpirySession()
  return result
}

export function removeToken() {
  return Cookies.remove(TokenKey)
}
