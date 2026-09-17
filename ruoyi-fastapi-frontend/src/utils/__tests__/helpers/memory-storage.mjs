// 测试共用的内存 Storage mock。默认按浏览器语义把写入值字符串化；
// throwOnWrite 模拟配额超限写失败，ignoreWrites 模拟静默丢写，
// initial 提供预置键值，values 暴露底层 Map 供直接断言。
export function memoryStorage({
  ignoreWrites = false,
  throwOnWrite = false,
  initial = {},
} = {}) {
  const values = new Map(Object.entries(initial))
  return {
    values,
    getItem(key) {
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      if (throwOnWrite) throw new Error('quota')
      if (!ignoreWrites) values.set(key, String(value))
    },
    removeItem(key) {
      values.delete(key)
    },
  }
}
