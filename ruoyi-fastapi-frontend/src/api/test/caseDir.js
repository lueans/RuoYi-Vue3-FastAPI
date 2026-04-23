import request from '@/utils/request'

export function listCaseDir(query) {
  return request({
    url: '/test/caseDir/list',
    method: 'get',
    params: query
  })
}

export function listCaseDirExcludeChild(dirId) {
  return request({
    url: '/test/caseDir/list/exclude/' + dirId,
    method: 'get'
  })
}

export function getCaseDir(dirId) {
  return request({
    url: '/test/caseDir/' + dirId,
    method: 'get'
  })
}

export function addCaseDir(data) {
  return request({
    url: '/test/caseDir',
    method: 'post',
    data: data
  })
}

export function updateCaseDir(data) {
  return request({
    url: '/test/caseDir',
    method: 'put',
    data: data
  })
}

export function delCaseDir(dirId) {
  return request({
    url: '/test/caseDir/' + dirId,
    method: 'delete'
  })
}
