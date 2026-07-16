#!/usr/bin/env node
// Minimal OpenAI-completions compatible chat server for coding-agent harness
// testing. Returns streaming SSE, branches on the previous turn's last role
// so a coding agent in `--print` / single-shot mode terminates cleanly.
//
// Usage:
//   node mock-openai-compat-server.js               # listens on 127.0.0.1:11305
//   MOCK_PORT=12345 node mock-openai-compat-server.js
//   MOCK_TARGET_FILE=src/foo.js node mock-openai-compat-server.js
//   MOCK_PATCH="<file contents>" node mock-openai-compat-server.js
//
// Behavior:
//   - POST /v1/chat/completions
//       If the last message in the request has role:"user"  → return a
//         single `write` tool call that creates MOCK_TARGET_FILE with
//         MOCK_PATCH as contents. (finish_reason: "tool_calls")
//       If the last message has role:"tool"                  → return a
//         short text completion "Done — wrote the file." with
//         finish_reason: "stop". This is what makes the agent
//         terminate instead of looping.
//   - GET  /v1/models → returns one fake model: MOCK_MODEL_ID
//
// The fixture file path is auto-detected by scanning the request messages
// for the first .py/.js/.ts/.go/.rs/.c/.cpp/.h filename, falling back to
// MOCK_TARGET_FILE.
//
// This avoids the two big gotchas when wrapping a coding agent around a
// mock LLM:
//   1. Plain-JSON responses hang agents that use SSE streaming
//      (see subprocess-sandbox SKILL.md gotcha #9).
//   2. A model that only ever returns tool_calls never lets a single-shot
//      coding agent exit, so the harness times out
//      (see subprocess-sandbox SKILL.md gotcha #8).
//
// Verified 2026-06-05 against GoblinBench CodingAgentRunner + real pi:
// the run reports OK in ~500ms with exactly 3 chat-completion requests
// (initial user prompt → tool result → final assistant text).

const http = require('http');

const PORT = parseInt(process.env.MOCK_PORT || '11305', 10);
const TARGET = process.env.MOCK_TARGET_FILE || 'src/main.py';
const PATCH = process.env.MOCK_PATCH ||
  'def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n';
const MODEL_ID = 'mock-lemonade-edit';

const s = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/v1/models') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      object: 'list',
      data: [{
        id: MODEL_ID,
        object: 'model',
        created: 0,
        owned_by: 'mock',
      }],
    }));
    return;
  }

  if (req.method === 'POST' && req.url === '/v1/chat/completions') {
    let raw = '';
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      // Parse the request to drive branching + filename detection.
      let fixture = TARGET;
      let lastHasToolResult = false;
      let msgCount = 0;
      try {
        const parsed = JSON.parse(raw);
        const msgs = parsed.messages || [];
        msgCount = msgs.length;
        if (msgs.length > 0) {
          const last = msgs[msgs.length - 1];
          lastHasToolResult = last.role === 'tool';
        }
        for (const m of msgs) {
          const match = (m.content || '').match(/([\w./_-]+\.(?:py|js|ts|go|rs|c|cpp|h))\b/);
          if (match) { fixture = match[1]; break; }
        }
      } catch (_) {}

      const ts = new Date().toISOString();
      process.stdout.write(
        `[${ts}] POST /v1/chat/completions msgs=${msgCount} lastRole=${lastHasToolResult ? 'tool' : 'user'}\n`);

      const chatId = 'chatcmpl-mock-' + Date.now();
      const finalText = 'Done — wrote the file.';

      // SSE chunks: role-only on first, then content deltas, then
      // finish_reason on the last non-empty chunk, then an empty
      // chunk to flush, then [DONE].
      const lines = lastHasToolResult
        ? [
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: { content: finalText }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [] },
          ]
        : [
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: { tool_calls: [{
                index: 0,
                id: 'call_' + Math.random().toString(36).slice(2, 10),
                type: 'function',
                function: { name: 'write', arguments: '' },
              }] }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: { tool_calls: [{
                index: 0,
                function: { arguments: JSON.stringify({ path: fixture, content: PATCH }) },
              }] }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: MODEL_ID,
              choices: [] },
          ];

      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      });
      for (const ln of lines) {
        res.write('data: ' + JSON.stringify(ln) + '\n\n');
      }
      res.write('data: [DONE]\n\n');
      res.end();
    });
    return;
  }

  res.writeHead(404).end();
});

s.listen(PORT, '127.0.0.1', () => {
  console.log('mock-openai-compat listening on http://127.0.0.1:' + PORT + '/v1');
});
