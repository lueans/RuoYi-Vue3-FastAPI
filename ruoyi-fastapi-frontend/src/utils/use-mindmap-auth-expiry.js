import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { isAuthSessionExpired, subscribeAuthExpiry } from './auth-expiry.js'

// Keep expiration reactive without exposing the token in notifications. A
// mounted-after-expiration panel must also stop before starting its first poll.
export function useMindmapAuthExpiry(token, onExpired = () => {}) {
  const expired = ref(isAuthSessionExpired(token()))
  let unsubscribe = null
  onMounted(() => {
    unsubscribe = subscribeAuthExpiry(() => {
      if (!isAuthSessionExpired(token())) return
      expired.value = true
      return onExpired()
    })
  })
  watch(token, nextToken => {
    if (nextToken && !isAuthSessionExpired(nextToken)) expired.value = false
  }, { flush: 'sync' })
  onScopeDispose(() => unsubscribe?.())
  return expired
}
