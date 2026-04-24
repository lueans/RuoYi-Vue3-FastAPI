# Local Customizations Log

All modifications to the vendored `simple-mind-map` source code should be documented here.
This file is essential for future upstream merges.

## Format

```
### YYYY-MM-DD - Brief Description
- **File**: path/to/modified/file.js
- **Change**: What was changed
- **Reason**: Why it was changed
```

## Customizations

### 2026-04-24 - Fix rich text node text display
- **File**: src/plugins/RichText.js
- **Change**: Added CSS margin/padding reset for block elements (p, h1-h6, ol, ul, blockquote, pre) inside `.smm-richtext-node-wrap`; Added null safety for `htmlEscape` call in `handleDataToRichText`
- **Reason**: When enabling rich text mode, node text is wrapped in `<p>` tags rendered via SVG foreignObject. The browser default `<p>` margins caused text to shift/clip inside nodes. Also, nodes with undefined text could crash the conversion.
