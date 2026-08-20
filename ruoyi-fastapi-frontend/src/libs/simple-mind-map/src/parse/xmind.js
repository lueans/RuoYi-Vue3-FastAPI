import JSZip from 'jszip'
import {
  getTextFromHtml,
  isUndef,
  stringifyJsonValueIterative
} from '../utils/index'
import {
  assertXmindDocumentSize,
  parseXmindXml,
  validateXmindArchive
} from './xmindImport'
import { mapXmindTreeIterative } from './xmindTree'
import {
  getSummaryText,
  getSummaryText2,
  getRoot,
  getItemByName,
  getElementsByType,
  addSummaryData,
  handleNodeImageFromXmind,
  handleNodeImageToXmind,
  getXmindContentXmlData,
  parseNodeGeneralizationToXmind
} from '../utils/xmind'

//  解析.xmind文件
const parseXmindFile = (file, handleMultiCanvas) => {
  return new Promise((resolve, reject) => {
    JSZip.loadAsync(file).then(
      async zip => {
        try {
          validateXmindArchive(zip.files)
          let content = ''
          let jsonFile = zip.files['content.json']
          let xmlFile = zip.files['content.xml'] || zip.files['/content.xml']
          if (jsonFile) {
            let json = assertXmindDocumentSize(
              await jsonFile.async('string'),
              'XMind JSON'
            )
            content = await transformXmind(json, zip.files, handleMultiCanvas)
          } else if (xmlFile) {
            let xml = await xmlFile.async('string')
            content = transformOldXmind(parseXmindXml(xml))
          }
          if (content) {
            resolve(content)
          } else {
            reject(new Error('解析失败'))
          }
        } catch (error) {
          reject(error)
        }
      },
      e => {
        reject(e)
      }
    )
  })
}

//  转换xmind数据
const transformXmind = async (content, files, handleMultiCanvas) => {
  content = JSON.parse(content)
  let data = null
  if (content.length > 1 && typeof handleMultiCanvas === 'function') {
    data = await handleMultiCanvas(content)
  }
  if (!data) {
    data = content[0]
  }
  const nodeTree = data?.rootTopic
  const waitLoadImageList = []
  const newTree = mapXmindTreeIterative({
    root: nodeTree,
    visit(node, newNode) {
      newNode.data = {
        // 节点内容
        text: isUndef(node.title) ? '' : node.title
      }
      // 节点备注
      if (node.notes) {
        const notesData = node.notes.realHTML || node.notes.plain
        newNode.data.note = notesData ? notesData.content || '' : ''
      }
      // 超链接
      if (node.href && /^https?:\/\//.test(node.href)) {
        newNode.data.hyperlink = node.href
      }
      // 标签
      if (Array.isArray(node.labels) && node.labels.length > 0) {
        newNode.data.tag = node.labels
      }
      // 图片
      handleNodeImageFromXmind(node, newNode, waitLoadImageList, files)
      // 概要
      const selfSummary = []
      const childrenSummary = []
      if (newNode._summary) selfSummary.push(newNode._summary)
      if (Array.isArray(node.summaries) && node.summaries.length > 0) {
        node.summaries.forEach(item => {
          addSummaryData(
            selfSummary,
            childrenSummary,
            () => getSummaryText(node, item.topicId),
            item.range
          )
        })
      }
      newNode.data.generalization = selfSummary
      newNode.children = []
      return {
        children: node.children?.attached,
        childrenSummary
      }
    },
    getChildren: (node, context) => context.meta.children,
    createChild(parentTarget, child, index, context) {
      const newChild = {}
      parentTarget.children.push(newChild)
      if (context.meta.childrenSummary[index]) {
        newChild._summary = context.meta.childrenSummary[index]
      }
      return newChild
    }
  })
  await Promise.all(waitLoadImageList)
  return newTree
}

//  转换旧版xmind数据，xmind8
const transformOldXmind = content => {
  const data = typeof content === 'string' ? JSON.parse(content) : content
  const elements = data?.elements
  const root = getRoot(elements)
  return mapXmindTreeIterative({
    root,
    visit(node, newNode) {
      const nodeElements = node.elements
      let nodeTitle = getItemByName(nodeElements, 'title')
      nodeTitle = nodeTitle?.elements?.[0]?.text
      newNode.data = {
        text: isUndef(nodeTitle) ? '' : nodeTitle
      }

      const notesElement = getItemByName(nodeElements, 'notes')
      const note = notesElement?.elements?.[0]?.elements?.[0]?.elements?.[0]?.text
      if (!isUndef(note)) newNode.data.note = note

      const hyperlink = node.attributes?.['xlink:href']
      if (hyperlink && /^https?:\/\//.test(hyperlink)) {
        newNode.data.hyperlink = hyperlink
      }

      const labelsElement = getItemByName(nodeElements, 'labels')
      if (Array.isArray(labelsElement?.elements)) {
        newNode.data.tag = labelsElement.elements
          .map(item => item?.elements?.[0]?.text)
          .filter(item => !isUndef(item))
      }

      const childrenItem = getItemByName(nodeElements, 'children')
      const children = getElementsByType(childrenItem?.elements, 'attached')
      const selfSummary = []
      const childrenSummary = []
      if (newNode._summary) selfSummary.push(newNode._summary)
      const summariesItem = getItemByName(nodeElements, 'summaries')
      if (Array.isArray(summariesItem?.elements)) {
        summariesItem.elements.forEach(item => {
          addSummaryData(
            selfSummary,
            childrenSummary,
            () => getSummaryText2(childrenItem, item?.attributes?.['topic-id']),
            item?.attributes?.range
          )
        })
      }
      newNode.data.generalization = selfSummary
      newNode.children = []
      return { children, childrenSummary }
    },
    getChildren: (node, context) => context.meta.children,
    createChild(parentTarget, child, index, context) {
      const newChild = {}
      parentTarget.children.push(newChild)
      if (context.meta.childrenSummary[index]) {
        newChild._summary = context.meta.childrenSummary[index]
      }
      return newChild
    }
  })
}

// 数据转换为xmind文件
// 直接转换为最新版本的xmind文件 2023.09.11172
const transformToXmind = async (data, name) => {
  const id = 'simpleMindMap_' + Date.now()
  const imageList = []
  // 转换核心数据
  const waitLoadImageList = []
  const newTree = mapXmindTreeIterative({
    root: data,
    visit(node, newNode, context) {
      const newData = {
        id: node.data.uid,
        structureClass: 'org.xmind.ui.logic.right',
        title: getTextFromHtml(node.data.text),
        children: {
          attached: []
        }
      }
      // 备注
      if (node.data.note !== undefined) {
        newData.notes = {
          realHTML: { content: node.data.note },
          plain: { content: node.data.note }
        }
      }
      // 超链接
      if (node.data.hyperlink !== undefined) {
        newData.href = node.data.hyperlink
      }
      // 标签
      if (node.data.tag !== undefined) {
        newData.labels = (node.data.tag || []).map(item => {
          return typeof item === 'object' && item !== null ? item.text : item
        })
      }
      // 图片必须写到 topic；根节点的 newNode 是 sheet，不能作为图片目标。
      handleNodeImageToXmind(
        node,
        newData,
        waitLoadImageList,
        imageList
      )

      if (context.isRoot) {
        newData.class = 'topic'
        newNode.id = id
        newNode.class = 'sheet'
        newNode.title = name
        newNode.extensions = []
        newNode.topicPositioning = 'fixed'
        newNode.topicOverlapping = 'overlap'
        newNode.coreVersion = '2.100.0'
        newNode.rootTopic = newData
      } else {
        Object.assign(newNode, newData)
      }

      const { summary, summaries } = parseNodeGeneralizationToXmind(node)
      if (summaries.length > 0) {
        newData.children.summary = summary
        newData.summaries = summaries
      }
      return {
        children: node.children,
        topic: newData
      }
    },
    getChildren: (node, context) => context.meta.children,
    createChild(parentTarget, child, index, context) {
      const newChild = {}
      context.meta.topic.children.attached.push(newChild)
      return newChild
    }
  })
  await Promise.all(waitLoadImageList)
  const contentData = [newTree]
  // 创建压缩包
  const zip = new JSZip()
  zip.file('content.json', stringifyJsonValueIterative(contentData))
  zip.file(
    'metadata.json',
    `{"modifier":"","dataStructureVersion":"2","creator":{"name":"mind-map"},"layoutEngineVersion":"3","activeSheetId":"${id}"}`
  )
  zip.file('content.xml', getXmindContentXmlData())
  const manifestData = {
    'file-entries': {
      'content.json': {},
      'metadata.json': {},
      'Thumbnails/thumbnail.png': {}
    }
  }
  // 图片
  if (imageList.length > 0) {
    imageList.forEach(item => {
      manifestData['file-entries']['resources/' + item.name] = {}
      const img = zip.folder('resources')
      img.file(item.name, item.data, { base64: true })
    })
  }
  zip.file('manifest.json', stringifyJsonValueIterative(manifestData))
  const zipData = await zip.generateAsync({ type: 'blob' })
  return zipData
}

export default {
  parseXmindFile,
  transformXmind,
  transformOldXmind,
  transformToXmind
}
