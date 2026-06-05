#!/usr/bin/env node
// Minimal OpenAI-completions compatible chat server for GoblinBench e2e tests.
// Returns a `write` tool call that mutates the workspace file, so we can
// verify the runner's file-change snapshot/diff actually fires.

const http = require('http');

const PORT = parseInt(process.env.MOCK_PORT || '11305', 10);
const TARGET = process.env.MOCK_TARGET_FILE || 'src/main.py';
const PATCH = process.env.MOCK_PATCH ||
  'def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n';

const s = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/v1/models') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      object: 'list',
      data: [{
        id: 'mock-lemonade-edit',
        object: 'model',
        created: 0,
        owned_by: 'mock',
      }],
    }));
    return;
  }
  if (req.method === 'POST' && req.url === '/v1/chat/completions') {
    const body = req.write; // unused, drain later
    let raw = '';
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      const ts = new Date().toISOString();
      let msgCount = 0, lastRole = '?', lastHasToolResult = false;
      try {
        const parsed = JSON.parse(raw);
        const msgs = parsed.messages || [];
        msgCount = msgs.length;
        if (msgCount > 0) {
          const last = msgs[msgCount - 1];
          lastRole = last.role;
          lastHasToolResult = last.role === 'tool';
        }
      } catch (_) {}
      process.stdout.write(`[${ts}] POST /v1/chat/completions msgs=${msgCount} lastRole=${lastRole}\n`);

      // Parse the request to find the fixture file path the model "sees"
      let fixture = TARGET;
      try {
        const parsed = JSON.parse(raw);
        for (const m of parsed.messages || []) {
          const match = (m.content || '').match(/([\w./_-]+\.(?:py|js|ts|go|rs|c|cpp|h))\b/);
          if (match) { fixture = match[1]; break; }
        }
      } catch (_) {}

      const chatId = 'chatcmpl-mock-' + Date.now();
      const isFollowup = lastHasToolResult;
      const finalText = 'Done — wrote the file.';
      const lines = isFollowup
        ? [
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: { content: finalText }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [] },
          ]
        : [
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: { tool_calls: [{
                index: 0, id: 'call_' + Math.random().toString(36).slice(2, 10), type: 'function',
                function: { name: 'write', arguments: '' },
              } ] }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: { tool_calls: [{
                index: 0, function: { arguments: JSON.stringify({ path: fixture, content: PATCH }) },
              } ] }, finish_reason: null }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
              choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }] },
            { id: chatId, object: 'chat.completion.chunk', created: 0, model: 'mock-lemonade-edit',
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
  console.log('mock-lemonade listening on http://127.0.0.1:' + PORT + '/v1');
});
