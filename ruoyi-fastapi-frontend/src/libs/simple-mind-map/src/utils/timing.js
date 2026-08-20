// 可取消的节流函数。取消后允许下一次调用重新开始计时。
export const throttle = (fn, time = 300, ctx) => {
  let timer = null
  const throttled = (...args) => {
    if (timer !== null) return
    timer = setTimeout(() => {
      timer = null
      fn.call(ctx, ...args)
    }, time)
  }
  throttled.cancel = () => {
    if (timer === null) return
    clearTimeout(timer)
    timer = null
  }
  return throttled
}

// 可取消的防抖函数。用于实例销毁时阻止延迟回调继续访问旧对象。
export const debounce = (fn, wait = 300, ctx) => {
  let timeout = null
  const debounced = (...args) => {
    if (timeout !== null) clearTimeout(timeout)
    timeout = setTimeout(() => {
      timeout = null
      fn.apply(ctx, args)
    }, wait)
  }
  debounced.cancel = () => {
    if (timeout === null) return
    clearTimeout(timeout)
    timeout = null
  }
  return debounced
}
