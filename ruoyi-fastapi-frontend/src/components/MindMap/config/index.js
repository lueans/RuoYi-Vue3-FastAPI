// Structure images
import logicalStructureImg from '../assets/img/structures/logicalStructure.jpg'
import logicalStructureLeftImg from '../assets/img/structures/logicalStructureLeft.jpg'
import mindMapImg from '../assets/img/structures/mindMap.jpg'
import organizationStructureImg from '../assets/img/structures/organizationStructure.jpg'
import catalogOrganizationImg from '../assets/img/structures/catalogOrganization.jpg'
import timelineImg from '../assets/img/structures/timeline.jpg'
import timeline2Img from '../assets/img/structures/timeline2.jpg'
import fishboneImg from '../assets/img/structures/fishbone.jpg'
import verticalTimelineImg from '../assets/img/structures/verticalTimeline.jpg'
import verticalTimeline2Img from '../assets/img/structures/verticalTimeline2.jpg'
import verticalTimeline3Img from '../assets/img/structures/verticalTimeline3.jpg'

export const layoutImgMap = {
  logicalStructure: logicalStructureImg,
  logicalStructureLeft: logicalStructureLeftImg,
  mindMap: mindMapImg,
  organizationStructure: organizationStructureImg,
  catalogOrganization: catalogOrganizationImg,
  timeline: timelineImg,
  timeline2: timeline2Img,
  fishbone: fishboneImg,
  verticalTimeline: verticalTimelineImg,
  verticalTimeline2: verticalTimeline2Img,
  verticalTimeline3: verticalTimeline3Img,
}

export const fontFamilyList = [
  { name: '宋体', value: '宋体, SimSun, Songti SC' },
  { name: '微软雅黑', value: '微软雅黑, Microsoft YaHei' },
  { name: '楷体', value: '楷体, 楷体_GB2312, SimKai, STKaiti' },
  { name: '黑体', value: '黑体, SimHei, Heiti SC' },
  { name: '隶书', value: '隶书, SimLi' },
  { name: 'Andale Mono', value: 'andale mono' },
  { name: 'Arial', value: 'arial, helvetica, sans-serif' },
  { name: 'arialBlack', value: 'arial black, avant garde' },
  { name: 'Comic Sans Ms', value: 'comic sans ms' },
  { name: 'Impact', value: 'impact, chicago' },
  { name: 'Times New Roman', value: 'times new roman' },
  { name: 'Sans-Serif', value: 'sans-serif' },
  { name: 'serif', value: 'serif' },
]

export const fontSizeList = [10, 12, 14, 16, 18, 24, 32, 48]

export const colorList = [
  '#4D4D4D', '#999999', '#FFFFFF', '#F44E3B', '#FE9200', '#FCDC00',
  '#DBDF00', '#A4DD00', '#68CCCA', '#73D8FF', '#AEA1FF', '#FDA1FF',
  '#333333', '#808080', '#cccccc', '#D33115', '#E27300', '#FCC400',
  '#B0BC00', '#68BC00', '#16A5A5', '#009CE0', '#7B64FF', '#FA28FF',
  '#000000', '#666666', '#B3B3B3', '#9F0500', '#C45100', '#FB9E00',
  '#808900', '#194D33', '#0C797D', '#0062B1', '#653294',
  'transparent'
]

export const lineWidthList = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

export const borderWidthList = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

export const borderRadiusList = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

export const borderDasharrayList = [
  { name: '实线', value: 'none' },
  { name: '虚线1', value: '5,5' },
  { name: '虚线2', value: '10,10' },
  { name: '虚线3', value: '20,10,5,5,5,10' },
  { name: '虚线4', value: '5,5,1,5' },
  { name: '虚线5', value: '15,10,5,10,15' },
  { name: '虚线6', value: '1,5' },
  { name: '虚线7', value: '6,4' },
]

export const lineStyleMap = {
  straight: `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="60" height="26"><path d="M18,14L30,14L30,5L42,5" fill="none" stroke="#000" stroke-width="2"></path><path d="M18,14L30,14L30,23L42,23" fill="none" stroke="#000" stroke-width="2"></path></svg>`,
  curve: `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="60" height="26"><path d="M18,14L30,14A12,-9 0 0 1 42,5" fill="none" stroke="#000" stroke-width="2"></path><path d="M18,14L30,14A12,9 0 0 0 42,23" fill="none" stroke="#000" stroke-width="2"></path></svg>`,
  direct: `<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="60" height="26"><path d="M18,14L30,14L42,5" fill="none" stroke="#000" stroke-width="2"></path><path d="M18,14L30,14L42,23" fill="none" stroke="#000" stroke-width="2"></path></svg>`
}

export const lineStyleList = [
  { name: '直线', value: 'straight' },
  { name: '曲线', value: 'curve' },
  { name: '直连', value: 'direct' },
]

export const rootLineKeepSameInCurveList = [
  { name: '括号', value: false },
  { name: '大括号', value: true },
]

export const shapeListMap = {
  rectangle: 'M 4 12 L 4 3 L 56 3 L 56 21 L 4 21 L 4 12 Z',
  diamond: 'M 4 12 L 30 3 L 56 12 L 30 21 L 4 12 Z',
  parallelogram: 'M 10 3 L 56 3 L 50 21 L 4 21 L 10 3 Z',
  roundedRectangle: 'M 13 3 L 47 3 A 9 9 0, 0 1 47 21 L 13 21 A 9 9 0, 0 1 13 3 Z',
  octagonalRectangle: 'M 4 12 L 4 9 L 10 3 L 50 3 L 56 9 L 56 15 L 50 21 L 10 21 L 4 15 L 4 12 Z',
  outerTriangularRectangle: 'M 4 12 L 10 3 L 50 3 L 56 12 L 50 21 L 10 21 L 4 12 Z',
  innerTriangularRectangle: 'M 10 12 L 4 3 L 56 3 L 50 12 L 56 21 L 4 21 L 10 12 Z',
  ellipse: 'M 4 12 A 26 9 0, 1, 0 30 3 A 26 9 0, 0, 0 4 12 Z',
  circle: 'M 21 12 A 9 9 0, 1, 0 30 3 A 9 9 0, 0, 0 21 12 Z'
}

export const shapeList = [
  { name: '矩形', value: 'rectangle' },
  { name: '菱形', value: 'diamond' },
  { name: '平行四边形', value: 'parallelogram' },
  { name: '圆角矩形', value: 'roundedRectangle' },
  { name: '八角矩形', value: 'octagonalRectangle' },
  { name: '外三角矩形', value: 'outerTriangularRectangle' },
  { name: '内三角矩形', value: 'innerTriangularRectangle' },
  { name: '椭圆', value: 'ellipse' },
  { name: '圆', value: 'circle' },
]

export const layoutList = [
  { name: '逻辑结构图', value: 'logicalStructure' },
  { name: '向左逻辑结构图', value: 'logicalStructureLeft' },
  { name: '思维导图', value: 'mindMap' },
  { name: '组织结构图', value: 'organizationStructure' },
  { name: '目录组织图', value: 'catalogOrganization' },
  { name: '时间轴', value: 'timeline' },
  { name: '时间轴2', value: 'timeline2' },
  { name: '竖向时间轴', value: 'verticalTimeline' },
  { name: '竖向时间轴2', value: 'verticalTimeline2' },
  { name: '鱼骨图', value: 'fishbone' },
]

export const layoutGroupList = [
  {
    name: '逻辑结构图',
    list: ['logicalStructure', 'logicalStructureLeft']
  },
  {
    name: '思维导图',
    list: ['mindMap']
  },
  {
    name: '组织结构图',
    list: ['organizationStructure']
  },
  {
    name: '目录组织图',
    list: ['catalogOrganization']
  },
  {
    name: '时间轴',
    list: ['timeline', 'timeline2', 'verticalTimeline', 'verticalTimeline2']
  },
  {
    name: '鱼骨图',
    list: ['fishbone']
  }
]

export const downTypeList = [
  { name: 'SMM', value: 'smm', icon: 'iconwenjian', desc: '可再次导入编辑' },
  { name: 'JSON', value: 'json', icon: 'iconjson', desc: '通用数据格式' },
  { name: 'PNG', value: 'png', icon: 'iconPNG', desc: '常用图片格式' },
  { name: 'SVG', value: 'svg', icon: 'iconSVG', desc: '矢量图格式' },
  { name: 'PDF', value: 'pdf', icon: 'iconpdf', desc: '适合查看浏览和打印' },
  { name: 'Markdown', value: 'md', icon: 'iconmarkdown', desc: '文本标记格式' },
  { name: 'XMind', value: 'xmind', icon: 'iconxmind', desc: 'XMind 软件格式' },
  { name: 'Txt', value: 'txt', icon: 'iconTXT', desc: '纯文字' },
]

const isMac = typeof navigator !== 'undefined' && navigator.platform.toUpperCase().indexOf('MAC') >= 0
const ctrl = isMac ? '⌘' : 'Ctrl'
const enter = isMac ? 'Return' : 'Enter'
const macFn = isMac ? 'fn + ' : ''

export const shortcutKeyList = [
  {
    type: '节点操作',
    list: [
      { icon: 'icontianjiazijiedian', name: '插入下级节点', value: 'Tab | Insert' },
      { icon: 'iconjiedian', name: '插入同级节点', value: enter },
      { icon: 'icondodeparent', name: '插入父节点', value: 'Shift + Tab' },
      { icon: 'iconshangyi', name: '上移节点', value: `${ctrl} + ↑` },
      { icon: 'iconxiayi', name: '下移节点', value: `${ctrl} + ↓` },
      { icon: 'icongaikuozonglan', name: '插入概要', value: `${ctrl} + G` },
      { icon: 'iconzhankai', name: '展开/收起节点', value: '/' },
      { icon: 'iconshanchu', name: '删除节点', value: 'Delete | Backspace' },
      { icon: 'iconshanchu', name: '仅删除当前节点', value: 'Shift + Backspace' },
      { icon: 'iconfuzhi', name: '复制节点', value: `${ctrl} + C` },
      { icon: 'iconjianqie', name: '剪切节点', value: `${ctrl} + X` },
      { icon: 'iconniantie', name: '粘贴节点', value: `${ctrl} + V` },
      { icon: 'iconbianji', name: '编辑节点', value: macFn + 'F2' },
      { icon: 'iconhuanhang', name: '文本换行', value: `Shift + ${enter}` },
      { icon: 'iconhoutui-shi', name: '回退', value: `${ctrl} + Z` },
      { icon: 'iconqianjin1', name: '前进', value: `${ctrl} + Y` },
      { icon: 'iconquanxuan', name: '全选', value: `${ctrl} + A` },
      { icon: 'iconquanxuan', name: '多选', value: `右键 / ${ctrl} + 左键` },
      { icon: 'iconzhengli', name: '一键整理布局', value: `${ctrl} + L` },
      { icon: 'iconsousuo', name: '搜索和替换', value: `${ctrl} + F` },
    ]
  },
  {
    type: '画布操作',
    list: [
      { icon: 'iconfangda', name: '放大', value: `${ctrl} + +` },
      { icon: 'iconsuoxiao', name: '缩小', value: `${ctrl} + -` },
      { icon: 'iconfangda', name: '放大/缩小', value: `${ctrl} + 鼠标滚动` },
      { icon: 'icondingwei', name: '回到根节点', value: `${ctrl} + ${enter}` },
      { icon: 'iconquanping1', name: '适应画布', value: `${ctrl} + i` },
    ]
  },
  {
    type: '大纲操作',
    list: [
      { icon: 'iconhuanhang', name: '文本换行', value: `Shift + ${enter}` },
      { icon: 'iconshanchu', name: '删除节点', value: 'Delete' },
      { icon: 'icontianjiazijiedian', name: '插入下级节点', value: 'Tab' },
      { icon: 'iconjiedian', name: '插入同级节点', value: enter },
      { icon: 'icondodeparent', name: '上移一个层级', value: 'Shift + Tab' },
    ]
  },
]

export const sidebarTriggerList = [
  { name: '格式', value: 'nodeStyle', icon: 'iconzhuti' },
  { name: '大纲', value: 'outline', icon: 'iconfuhao-dagangshu' },
  { name: '公式', value: 'formulaSidebar', icon: 'icongongshi' },
  { name: '设置', value: 'setting', icon: 'iconshezhi' },
  { name: '快捷键', value: 'shortcutKey', icon: 'iconjianpan' },
  { name: '版本历史', value: 'versionHistory', icon: 'iconlishijilu' },
  { name: '协作者', value: 'collaboratorManager', icon: 'iconxiezuo' },
]

export const alignList = [
  { name: '左对齐', value: 'left' },
  { name: '居中对齐', value: 'center' },
  { name: '右对齐', value: 'right' },
]

export const linearGradientDirList = [
  { name: '从左到右', value: '1', start: [0, 0], end: [1, 0] },
  { name: '从右到左', value: '2', start: [1, 0], end: [0, 0] },
  { name: '从上到下', value: '3', start: [0, 0], end: [0, 1] },
  { name: '从下到上', value: '4', start: [0, 1], end: [0, 0] },
  { name: '从左上到右下', value: '5', start: [0, 0], end: [1, 1] },
  { name: '从左下到右上', value: '6', start: [0, 1], end: [1, 0] },
  { name: '从右上到左下', value: '7', start: [1, 0], end: [0, 1] },
  { name: '从右下到左上', value: '8', start: [1, 1], end: [0, 0] },
]

export const imgPlacementList = [
  { name: '上方', value: 'top' },
  { name: '下方', value: 'bottom' },
  { name: '左侧', value: 'left' },
  { name: '右侧', value: 'right' },
]

export const tagPlacementList = [
  { name: '右侧', value: 'right' },
  { name: '底部', value: 'bottom' },
]

export const backgroundRepeatList = [
  { name: '不重复', value: 'no-repeat' },
  { name: '重复', value: 'repeat' },
  { name: '水平方向重复', value: 'repeat-x' },
  { name: '垂直方向重复', value: 'repeat-y' },
]

export const backgroundPositionList = [
  { name: '默认', value: '0% 0%' },
  { name: '左上', value: 'left top' },
  { name: '左中', value: 'left center' },
  { name: '左下', value: 'left bottom' },
  { name: '右上', value: 'right top' },
  { name: '右中', value: 'right center' },
  { name: '右下', value: 'right bottom' },
  { name: '中上', value: 'center top' },
  { name: '居中', value: 'center center' },
  { name: '中下', value: 'center bottom' },
]

export const backgroundSizeList = [
  { name: '自动', value: 'auto' },
  { name: '覆盖', value: 'cover' },
  { name: '保持', value: 'contain' },
]

export const rainbowLinesOptions = [
  { value: 'close' },
  {
    value: 'colors1',
    list: ['rgb(255, 213, 73)', 'rgb(255, 136, 126)', 'rgb(107, 225, 141)', 'rgb(151, 171, 255)', 'rgb(129, 220, 242)', 'rgb(255, 163, 125)', 'rgb(152, 132, 234)']
  },
  {
    value: 'colors2',
    list: ['rgb(248, 93, 93)', 'rgb(255, 151, 84)', 'rgb(255, 214, 69)', 'rgb(73, 205, 140)', 'rgb(64, 192, 255)', 'rgb(84, 110, 214)', 'rgb(164, 93, 220)']
  },
  {
    value: 'colors3',
    list: ['rgb(140, 240, 231)', 'rgb(74, 210, 255)', 'rgb(65, 168, 243)', 'rgb(49, 128, 205)', 'rgb(188, 226, 132)', 'rgb(113, 215, 123)', 'rgb(120, 191, 109)']
  },
  {
    value: 'colors4',
    list: ['rgb(169, 98, 99)', 'rgb(245, 125, 123)', 'rgb(254, 183, 168)', 'rgb(251, 218, 171)', 'rgb(138, 163, 181)', 'rgb(131, 127, 161)', 'rgb(84, 83, 140)']
  },
  {
    value: 'colors5',
    list: ['rgb(255, 229, 142)', 'rgb(254, 158, 41)', 'rgb(248, 119, 44)', 'rgb(232, 82, 80)', 'rgb(182, 66, 98)', 'rgb(99, 54, 99)', 'rgb(65, 40, 82)']
  },
  {
    value: 'colors6',
    list: ['rgb(171, 227, 209)', 'rgb(107, 201, 196)', 'rgb(55, 170, 169)', 'rgb(18, 135, 131)', 'rgb(74, 139, 166)', 'rgb(75, 105, 150)', 'rgb(57, 75, 133)']
  }
]

// Constants for layout support
export const supportLineStyleLayoutsMap = {
  curve: ['logicalStructure', 'logicalStructureLeft', 'mindMap', 'verticalTimeline', 'organizationStructure'],
  direct: ['logicalStructure', 'logicalStructureLeft', 'mindMap', 'organizationStructure', 'verticalTimeline']
}

export const supportLineRadiusLayouts = [
  'logicalStructure', 'logicalStructureLeft', 'mindMap', 'verticalTimeline'
]

export const supportNodeUseLineStyleLayouts = [
  'logicalStructure', 'logicalStructureLeft', 'mindMap', 'catalogOrganization', 'organizationStructure'
]

export const supportRootLineKeepSameInCurveLayouts = [
  'mindMap', 'organizationStructure'
]

export const formulaList = [
  'a^2',
  'a_2',
  'a^{2+2}',
  'a_{i,j}',
  'x_2^3',
  '\\overbrace{1+2+\\cdots+100}',
  '\\sum_{k=1}^N k^2',
  '\\lim_{n \\to \\infty}x_n',
  '\\int_{-N}^{N} e^x\\, dx',
  '\\sqrt{3}',
  '\\sqrt[n]{3}',
  '\\sin\\theta',
  '\\log X',
  '\\log_{10}',
  '\\log_\\alpha X',
  '\\lim_{t\\to n}T',
  '\\frac{1}{2}=0.5',
  '\\binom{n}{k}',
  '\\begin{matrix}x & y \\\\z & v\\end{matrix}',
  '\\begin{cases}3x + 5y + z \\\\7x - 2y + 4z \\\\-6x + 3y + 2z\\end{cases}'
]

export const defaultData = {
  data: { text: '中心主题', expand: true },
  children: [
    {
      data: { text: '分支主题1', expand: true },
      children: [
        { data: { text: '子主题1' }, children: [] },
        { data: { text: '子主题2' }, children: [] },
      ]
    },
    {
      data: { text: '分支主题2', expand: true },
      children: [
        { data: { text: '子主题3' }, children: [] },
        { data: { text: '子主题4' }, children: [] },
      ]
    },
    {
      data: { text: '分支主题3', expand: true },
      children: []
    }
  ]
}
