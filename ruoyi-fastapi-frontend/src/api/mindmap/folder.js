import request from '@/utils/request'

// 获取文件夹树
export function getFolderTree() {
  return request({
    url: '/mindmap/folder/tree',
    method: 'get'
  })
}

// 新建文件夹
export function addFolder(data) {
  return request({
    url: '/mindmap/folder',
    method: 'post',
    data: data
  })
}

// 编辑文件夹（重命名/移动）
export function updateFolder(data) {
  return request({
    url: '/mindmap/folder',
    method: 'put',
    data: data
  })
}

// 文件夹排序
export function sortFolders(data) {
  return request({
    url: '/mindmap/folder/sort',
    method: 'put',
    data: data
  })
}

// 删除文件夹
export function deleteFolder(folderId) {
  return request({
    url: '/mindmap/folder/' + folderId,
    method: 'delete'
  })
}

// 移动脑图到文件夹
export function moveMindmaps(data) {
  return request({
    url: '/mindmap/move',
    method: 'put',
    data: data
  })
}
