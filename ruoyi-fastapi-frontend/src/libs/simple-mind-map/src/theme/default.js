//  默认主题 - 现代SaaS风格，极简、扁平化、高信息密度
export default {
  // 节点内边距
  paddingX: 20,
  paddingY: 10,
  // 图片显示的最大宽度
  imgMaxWidth: 200,
  // 图片显示的最大高度
  imgMaxHeight: 100,
  // icon的大小
  iconSize: 20,
  // 连线的粗细
  lineWidth: 1,
  // 连线的颜色（品牌宝蓝色）
  lineColor: '#4D73FF',
  // 连线样式
  lineDasharray: 'none',
  // 连线是否开启流动效果，仅在虚线时有效（需要注册LineFlow插件）
  lineFlow: false,
  // 流动效果一个周期的时间，单位：s
  lineFlowDuration: 1,
  // 流动方向是否是从父节点到子节点
  lineFlowForward: true,
  // 连线风格：贝塞尔曲线
  lineStyle: 'curve',
  // 曲线连接时，根节点和其他节点的连接线样式保持统一
  rootLineKeepSameInCurve: true,
  // 曲线连接时，根节点连线起始位置
  rootLineStartPositionKeepSameInCurve: false,
  // 直线连接(straight)时，连线的圆角大小
  lineRadius: 5,
  // 连线是否显示标记
  showLineMarker: false,
  // 概要连线的粗细
  generalizationLineWidth: 1,
  // 概要连线的颜色（品牌蓝）
  generalizationLineColor: '#4D73FF',
  // 概要曲线距节点的距离
  generalizationLineMargin: 0,
  // 概要节点距节点的距离
  generalizationNodeMargin: 20,
  // 关联线默认状态的粗细
  associativeLineWidth: 2,
  // 关联线默认状态的颜色
  associativeLineColor: '#333333',
  // 关联线激活状态的粗细
  associativeLineActiveWidth: 8,
  // 关联线激活状态的颜色（品牌蓝）
  associativeLineActiveColor: '#4D73FF',
  // 关联线样式
  associativeLineDasharray: '6,4',
  // 关联线文字颜色
  associativeLineTextColor: '#333333',
  // 关联线文字大小
  associativeLineTextFontSize: 14,
  // 关联线文字行高
  associativeLineTextLineHeight: 1.2,
  // 关联线文字字体
  associativeLineTextFontFamily: '微软雅黑, Microsoft YaHei',
  // 背景颜色（纯白画布）
  backgroundColor: '#FFFFFF',
  // 背景图片
  backgroundImage: 'none',
  // 背景重复
  backgroundRepeat: 'no-repeat',
  // 设置背景图像的起始位置
  backgroundPosition: 'center center',
  // 设置背景图片大小
  backgroundSize: 'cover',
  // 节点使用只有底边横线的样式
  nodeUseLineStyle: false,
  // 根节点样式（品牌宝蓝色实心填充，带轻微投影感）
  root: {
    shape: 'rectangle',
    fillColor: '#4D73FF',
    fontFamily: '微软雅黑, Microsoft YaHei',
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
    fontStyle: 'normal',
    borderColor: 'transparent',
    borderWidth: 0,
    borderDasharray: 'none',
    borderRadius: 6,
    textDecoration: 'none',
    gradientStyle: false,
    startColor: '#4D73FF',
    endColor: '#fff',
    startDir: [0, 0],
    endDir: [1, 0],
    lineColor: '#4D73FF',
    lineWidth: 2,
    lineMarkerDir: 'end',
    hoverRectColor: '#4D73FF',
    hoverRectRadius: 6,
    textAlign: 'left',
    imgPlacement: 'top',
    tagPlacement: 'bottom'
  },
  // 二级节点样式（分组节点，浅灰背景）
  second: {
    shape: 'rectangle',
    marginX: 70,
    marginY: 25,
    fillColor: '#F5F5F5',
    fontFamily: '微软雅黑, Microsoft YaHei',
    color: '#333333',
    fontSize: 18,
    fontWeight: '500',
    fontStyle: 'normal',
    borderColor: 'transparent',
    borderWidth: 0,
    borderDasharray: 'none',
    borderRadius: 6,
    textDecoration: 'none',
    gradientStyle: false,
    startColor: '#F5F5F5',
    endColor: '#fff',
    startDir: [0, 0],
    endDir: [1, 0],
    lineColor: '#4D73FF',
    lineWidth: 1,
    lineMarkerDir: 'end',
    hoverRectColor: '#4D73FF',
    hoverRectRadius: 6,
    textAlign: 'left',
    imgPlacement: 'top',
    tagPlacement: 'bottom'
  },
  // 三级及以下节点样式（叶子节点，纯文本展示）
  node: {
    shape: 'rectangle',
    marginX: 60,
    marginY: 20,
    fillColor: 'transparent',
    fontFamily: '微软雅黑, Microsoft YaHei',
    color: '#333333',
    fontSize: 16,
    fontWeight: 'normal',
    fontStyle: 'normal',
    borderColor: 'transparent',
    borderWidth: 0,
    borderRadius: 6,
    borderDasharray: 'none',
    textDecoration: 'none',
    gradientStyle: false,
    startColor: '#F5F5F5',
    endColor: '#fff',
    startDir: [0, 0],
    endDir: [1, 0],
    lineColor: '#4D73FF',
    lineWidth: 1,
    lineMarkerDir: 'end',
    hoverRectColor: '#4D73FF',
    hoverRectRadius: 6,
    textAlign: 'left',
    imgPlacement: 'top',
    tagPlacement: 'bottom'
  },
  // 概要节点样式
  generalization: {
    shape: 'rectangle',
    marginX: 70,
    marginY: 25,
    fillColor: '#fff',
    fontFamily: '微软雅黑, Microsoft YaHei',
    color: '#333333',
    fontSize: 16,
    fontWeight: 'normal',
    fontStyle: 'normal',
    borderColor: '#dee0e3',
    borderWidth: 1,
    borderDasharray: 'none',
    borderRadius: 6,
    textDecoration: 'none',
    gradientStyle: false,
    startColor: '#F5F5F5',
    endColor: '#fff',
    startDir: [0, 0],
    endDir: [1, 0],
    hoverRectColor: '#4D73FF',
    hoverRectRadius: 6,
    textAlign: 'left',
    imgPlacement: 'top',
    tagPlacement: 'bottom'
  }
}

// 检测主题配置是否是节点大小无关的
const nodeSizeIndependenceList = [
  'lineWidth',
  'lineColor',
  'lineDasharray',
  'lineStyle',
  'generalizationLineWidth',
  'generalizationLineColor',
  'associativeLineWidth',
  'associativeLineColor',
  'associativeLineActiveWidth',
  'associativeLineActiveColor',
  'associativeLineTextColor',
  'associativeLineTextFontSize',
  'associativeLineTextLineHeight',
  'associativeLineTextFontFamily',
  'backgroundColor',
  'backgroundImage',
  'backgroundRepeat',
  'backgroundPosition',
  'backgroundSize',
  'rootLineKeepSameInCurve',
  'rootLineStartPositionKeepSameInCurve',
  'showLineMarker',
  'lineRadius',
  'hoverRectColor',
  'hoverRectRadius',
  'lineFlow',
  'lineFlowDuration',
  'lineFlowForward',
  'textAlign'
]
export const checkIsNodeSizeIndependenceConfig = config => {
  let keys = Object.keys(config)
  for (let i = 0; i < keys.length; i++) {
    if (
      !nodeSizeIndependenceList.find(item => {
        return item === keys[i]
      })
    ) {
      return false
    }
  }
  return true
}

// 连线的样式
export const lineStyleProps = [
  'lineColor',
  'lineDasharray',
  'lineWidth',
  'lineMarkerDir',
  'lineFlow',
  'lineFlowDuration',
  'lineFlowForward'
]
