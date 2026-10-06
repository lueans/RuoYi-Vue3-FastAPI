// import JsPDF from '../utils/jspdf'
import { PDFDocument } from 'pdf-lib'
import { readBlob } from '../utils/index'
import { abortableExport, loadExportImage, throwIfExportAborted } from '../utils/exportSession'

//  导出PDF插件，需要通过Export插件使用
class ExportPDF {
  //  构造函数
  constructor(opt) {
    this.mindMap = opt.mindMap
  }

  //  使用pdf-lib库导出为pdf
  async pdf(img, { signal } = {}) {
    const image = await loadExportImage(img, signal)
    const imageWidth = image.width
    const imageHeight = image.height
    image.src = ''
    throwIfExportAborted(signal)
    const pdfDoc = await abortableExport(PDFDocument.create(), signal)
    throwIfExportAborted(signal)
    const page = pdfDoc.addPage()
    page.setSize(imageWidth, imageHeight)
    const pngImage = await abortableExport(pdfDoc.embedPng(img), signal)
    throwIfExportAborted(signal)
    page.drawImage(pngImage, {
      x: 0,
      y: 0,
      width: imageWidth,
      height: imageHeight
    })
    const pdfBytes = await abortableExport(pdfDoc.save(), signal)
    throwIfExportAborted(signal)
    return readBlob(new Blob([pdfBytes]), { signal })
  }

  //  使用jspdf库导出为pdf
  // async pdf(name, img) {
  //   return new Promise((resolve, reject) => {
  //     const image = new Image()
  //     image.onload = () => {
  //       const imageWidth = image.width
  //       const imageHeight = image.height
  //       const pdf = new JsPDF({
  //         unit: 'px',
  //         format: [imageWidth, imageHeight],
  //         compress: true,
  //         hotfixes: ['px_scaling'],
  //         orientation: imageWidth > imageHeight ? 'landscape' : 'portrait'
  //       })
  //       pdf.addImage(img, 'PNG', 0, 0, imageWidth, imageHeight)
  //       pdf.save(name)
  //       resolve()
  //     }
  //     image.onerror = e => {
  //       reject(e)
  //     }
  //     image.src = img
  //   })
  // }
}

ExportPDF.instanceName = 'doExportPDF'

export default ExportPDF
