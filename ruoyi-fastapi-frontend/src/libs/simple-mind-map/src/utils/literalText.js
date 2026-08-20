// 按普通文本语义替换全部匹配，避免正则元字符和 $ 替换模板改变用户输入。
export const replaceAllLiteralText = (value, searchText, replaceText) => {
  const source = String(value ?? '')
  const search = String(searchText ?? '')
  if (!search) return source
  return source.split(search).join(String(replaceText ?? ''))
}
