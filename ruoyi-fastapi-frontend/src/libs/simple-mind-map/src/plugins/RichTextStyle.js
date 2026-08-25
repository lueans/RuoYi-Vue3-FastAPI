export const RICH_TEXT_NODE_CSS = `
  .smm-richtext-node-wrap {
    word-break: break-all;
    user-select: none;
  }

  .smm-richtext-node-wrap p,
  .smm-richtext-node-wrap h1,
  .smm-richtext-node-wrap h2,
  .smm-richtext-node-wrap h3,
  .smm-richtext-node-wrap h4,
  .smm-richtext-node-wrap h5,
  .smm-richtext-node-wrap h6,
  .smm-richtext-node-wrap ol,
  .smm-richtext-node-wrap ul,
  .smm-richtext-node-wrap blockquote,
  .smm-richtext-node-wrap pre {
    margin: 0;
    padding: 0;
  }

  .ql-editor .ql-align-left,
  .smm-richtext-node-wrap .ql-align-left {
    text-align: left;
  }

  .smm-richtext-node-wrap .ql-align-right {
    text-align: right;
  }

  .smm-richtext-node-wrap .ql-align-center {
    text-align: center;
  }
`

export default RICH_TEXT_NODE_CSS
