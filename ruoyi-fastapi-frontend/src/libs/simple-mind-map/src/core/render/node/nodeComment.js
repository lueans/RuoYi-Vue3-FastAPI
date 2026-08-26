import { G, Rect, Text } from '@svgdotjs/svg.js'

function createCommentNode() {
  this._commentGroup = new G()
  this._commentGroup.addClass('smm-node-comment')
  this._commentGroup.css({ cursor: 'pointer' })
  this._commentGroup.on('click', event => {
    event.stopPropagation()
    this.mindMap.emit('node_comment_click', this, event)
  })
  this._commentGroup.on('keydown', event => {
    if (!['Enter', ' '].includes(event.key)) return
    event.preventDefault()
    event.stopPropagation()
    this.mindMap.emit('node_comment_click', this, event)
  })
  this.group.add(this._commentGroup)
  this.updateCommentNode()
}

function updateCommentNode() {
  if (!this._commentGroup) return
  const count = Math.max(0, Number(this.commentCount) || 0)
  this._commentGroup.clear()
  if (count <= 0) {
    this._commentGroup.hide()
    return
  }
  const displayCount = count > 99 ? '99+' : String(count)
  const badgeWidth = displayCount.length >= 3 ? 28 : (displayCount.length === 2 ? 23 : 19)
  const badgeHeight = 19
  const background = new Rect()
    .size(badgeWidth, badgeHeight)
    .radius(7)
    .fill('#3370ff')
  const label = new Text()
    .text(displayCount)
    .fill('#fff')
    .css({
      'font-family': 'Arial, sans-serif',
      'font-size': '11px',
      'font-weight': '600',
    })
  label.center(badgeWidth / 2, badgeHeight / 2 + 0.5)
  this._commentGroup.add(background).add(label)
  this._commentGroup
    .attr({
      role: 'button',
      tabindex: 0,
      'aria-label': `${count} 条待处理评论`,
    })
    .x(this.width - badgeWidth / 2)
    .y(this.height - 4)
    .show()
}

function setCommentCount(count) {
  const nextCount = Math.max(0, Number(count) || 0)
  if (this.commentCount === nextCount) return
  this.commentCount = nextCount
  this.updateCommentNode()
}

export default {
  createCommentNode,
  updateCommentNode,
  setCommentCount,
}
