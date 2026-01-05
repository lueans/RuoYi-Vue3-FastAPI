import request from '@/utils/request'

// 查询文件列表
export function listFile(query) {
  return request({
    url: '/system/file/list',
    method: 'get',
    params: query
  })
}

// 删除文件
export function delFile(fileId) {
  return request({
    url: '/system/file/' + fileId,
    method: 'delete'
  })
}

// 上传文件
export function uploadFile(data) {
  return request({
    url: '/system/file/upload',
    method: 'post',
    data: data,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
