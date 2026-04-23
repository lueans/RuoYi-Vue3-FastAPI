import request from '@/utils/request'

// 查询业务线列表
export function listBusinessLine(query) {
  return request({
    url: '/test/businessLine/list',
    method: 'get',
    params: query
  })
}

// 查询业务线列表（排除节点）
export function listBusinessLineExcludeChild(lineId) {
  return request({
    url: '/test/businessLine/list/exclude/' + lineId,
    method: 'get'
  })
}

// 查询业务线详细
export function getBusinessLine(lineId) {
  return request({
    url: '/test/businessLine/' + lineId,
    method: 'get'
  })
}

// 新增业务线
export function addBusinessLine(data) {
  return request({
    url: '/test/businessLine',
    method: 'post',
    data: data
  })
}

// 修改业务线
export function updateBusinessLine(data) {
  return request({
    url: '/test/businessLine',
    method: 'put',
    data: data
  })
}

// 删除业务线
export function delBusinessLine(lineId) {
  return request({
    url: '/test/businessLine/' + lineId,
    method: 'delete'
  })
}
