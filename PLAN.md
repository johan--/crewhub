# Plan: Interleaved Content Blocks in Live Chat

## Problem

When an agent responds with `text → tool_use → text → tool_use → text`, the live chat flattens it:
- All text is concatenated into one string (`content: string`)
- Tool calls are collected into a separate array (`tools: ToolCallData[]`)
- Rendering shows all tools first, then all text as one block

Zen mode's `SessionHistoryView` already handles this correctly by using `content: SessionContentBlock[]`.

## Approach

Migrate the live chat pipeline from `content: string` + separate `tools`/`thinking` arrays to an ordered `content: ContentBlock[]` model — matching how zen mode works.

---

## Step 1: Backend — Interleaved content blocks from history endpoint

**File: `backend/app/routes/chat.py`**

Replace `_extract_content_parts()` (which separates text/tools/thinking into 3 lists) with `_extract_content_blocks()` that returns a single ordered list:

```python
def _extract_content_blocks(raw_content, raw: bool) -> list[dict]:
    """Return content blocks in original order, preserving interleaving."""
    blocks = []
    for block in raw_content:
        if block["type"] == "text":
            blocks.append({"type": "text", "text": block["text"]})
        elif block["type"] == "tool_use":
            blocks.append({"type": "tool_use", "name": ..., "status": "called", ...})
        elif block["type"] == "thinking":
            blocks.append({"type": "thinking", "thinking": block["thinking"]})
    return blocks
```

Update `_build_history_message()`:
- Set `content` to the block array instead of `"\n".join(content_parts)`
- Remove separate `tools` and `thinking` fields from the response payload

---

## Step 2: Backend — Emit structured SSE events during streaming

**File: `backend/app/services/cc_chat.py`**

Change the queue from `str` items to `dict` items:
- Text deltas: `{"type": "text_delta", "text": "..."}`
- Tool use blocks: `{"type": "tool_use", "name": "...", "status": "called", "input": {...}}`
- Thinking blocks: `{"type": "thinking", "thinking": "..."}`

In `on_output()`, when parsing `assistant` events, also emit tool_use and thinking blocks (currently only text is emitted).

**File: `backend/app/routes/chat.py`** streaming endpoint

Change the SSE generator to emit two event types:
- `event: delta` → `data: {"type": "text_delta", "text": "..."}` (text chunks — backward compatible since `parsed.text` still works)
- `event: content_block` → `data: {"type": "tool_use"|"thinking", ...}` (new structured blocks)

---

## Step 3: Frontend — New data model

**File: `frontend/src/hooks/useStreamingChat.ts`**

```typescript
export interface ContentBlock {
  type: 'text' | 'tool_use' | 'tool_result' | 'thinking'
  text?: string
  name?: string
  status?: string
  input?: Record<string, unknown>
  result?: string
  thinking?: string
}

export interface ChatMessageData {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: ContentBlock[]          // Changed from string
  timestamp: number
  tokens?: number
  isStreaming?: boolean
}
```

Remove `ToolCallData`, `tools`, and `thinking` fields.

---

## Step 4: Frontend — Handle streaming with content blocks

**File: `frontend/src/services/chatStreamService.ts`**

Add new callback and handle new SSE event type:

```typescript
export interface StreamCallbacks {
  onChunk: (text: string) => void
  onContentBlock: (block: ContentBlock) => void   // NEW
  onDone: () => void
  onError: (error: string) => void
}
```

In `processEventBatch()`, handle `event: content_block` by calling `callbacks.onContentBlock(parsed)`.

**File: `frontend/src/hooks/useStreamingChat.ts`**

Replace single `pendingContentRef: string` with:
- `contentBlocksRef = useRef<ContentBlock[]>([])`
- `pendingTextRef = useRef<string>('')`

On `onChunk` (text delta):
```
pendingTextRef.current += chunk
```

On `onContentBlock` (tool/thinking):
```
// Close current text block
if (pendingTextRef.current) {
  contentBlocksRef.current.push({type: 'text', text: pendingTextRef.current})
  pendingTextRef.current = ''
}
contentBlocksRef.current.push(block)
```

On `flushPendingContent` (throttled UI update):
```
const blocks = [...contentBlocksRef.current]
if (pendingTextRef.current) blocks.push({type: 'text', text: pendingTextRef.current})
setMessages(prev => prev.map(m => m.id === id ? {...m, content: blocks} : m))
```

On `onDone`:
```
const blocks = [...contentBlocksRef.current]
if (pendingTextRef.current) blocks.push({type: 'text', text: pendingTextRef.current})
setMessages(prev => prev.map(m => m.id === id ? {...m, content: blocks, isStreaming: false} : m))
```

---

## Step 5: Frontend — Render content blocks in order

**File: `frontend/src/components/chat/ChatMessageBubble.tsx`**

Replace the current rendering pattern:
```tsx
// BEFORE: thinking → tools → text (all separate, not interleaved)
{msg.thinking?.map(...)}
{msg.tools?.map(...)}
{cleanText && <span dangerouslySetInnerHTML={...} />}
```

With ordered block rendering:
```tsx
// AFTER: blocks rendered in original order
{msg.content.map((block, i) => {
  if (block.type === 'text') return <TextBlock key={i} text={block.text} ... />
  if (block.type === 'tool_use') return <ToolCallBlock key={i} tool={block} ... />
  if (block.type === 'thinking') return <ThinkingBlock key={i} content={block.thinking} ... />
})}
```

The existing `ToolCallBlock` and `ThinkingBlock` components can be reused with minor prop adjustments to accept `ContentBlock` instead of `ToolCallData`.

Media attachments and OpenClaw tag stripping: extract from the combined text of all text blocks before rendering (same logic, just iterate text blocks).

User messages: wrap `content: string` → `content: [{type: 'text', text: string}]` when creating user messages.

---

## Step 6: Update tests

- `ChatMessageBubble.test.tsx` — update `baseMsg` to use `content: ContentBlock[]`
- `MobileAgentChat.test.tsx` — update mock messages

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/routes/chat.py` | `_extract_content_blocks()`, update `_build_history_message()` |
| `backend/app/services/cc_chat.py` | Structured queue items, emit tool/thinking blocks |
| `frontend/src/hooks/useStreamingChat.ts` | New `ContentBlock` type, block-array streaming |
| `frontend/src/services/chatStreamService.ts` | Handle `content_block` SSE events |
| `frontend/src/components/chat/ChatMessageBubble.tsx` | Block-ordered rendering |
| `frontend/src/test/chat/ChatMessageBubble.test.tsx` | Update test data |
| `frontend/src/test/mobile/MobileAgentChat.test.tsx` | Update mock data |

## Risk / Notes

- **OpenClaw compatibility**: OpenClaw streaming still only emits text deltas — that's fine, it will just produce messages with a single text block (same visual result as today)
- **No separate `tools`/`thinking` fields**: Everything is in the ordered `content` array. This is cleaner and matches zen mode's model.
- **Streaming UX**: During streaming, text accumulates in the current text block. When a tool event arrives mid-stream, it visually breaks up the text. Once complete, history reload gives the definitive interleaved view.
