export function getNodeEditLeaseBlockedMessage(reason, users = []) {
  if (reason === 'readonly') {
    return '当前脑图为只读状态，无法编辑节点'
  }
  if (reason === 'connecting') {
    return '实时协作正在连接，暂不能编辑节点，请稍后重试'
  }
  if (reason !== 'occupied') {
    return '实时协作服务暂不可用，节点编辑已暂停，请稍后重试'
  }
  const editorName = users[0]?.name
  return editorName
    ? `${editorName}正在编辑此节点，请稍后再试`
    : '其他协作者正在编辑此节点，请稍后再试'
}
