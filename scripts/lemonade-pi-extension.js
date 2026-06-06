const DEFAULT_URL = "http://192.168.1.23:13305";

function serverUrl() {
  return (process.env.LEMONADE_URL ?? DEFAULT_URL).replace(/\/$/, "");
}

async function fetchLemonadeModels(baseUrl) {
  const res = await fetch(`${baseUrl}/v1/models`);
  if (!res.ok) throw new Error(`/v1/models returned HTTP ${res.status}`);
  const payload = await res.json();
  return payload.data ?? [];
}

function toProviderModels(data) {
  return data
    .filter((m) => m.downloaded !== false)
    .map((m) => ({
      id: m.id,
      name: m.id,
      reasoning: m.labels?.includes("reasoning") ?? false,
      input: m.labels?.includes("vision") ? ["text", "image"] : ["text"],
      contextWindow: m.max_context_window ?? 128000,
      maxTokens: Math.floor((m.max_context_window ?? 32768) / 4),
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    }));
}

function registerLemonade(pi, baseUrl, models) {
  pi.registerProvider("lemonade", {
    name: "Lemonade",
    baseUrl: `${baseUrl}/v1`,
    apiKey: "lemonade",
    api: "openai-completions",
    compat: {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsUsageInStreaming: false,
    },
    models: toProviderModels(models),
  });
}

export default async function lemonade(pi) {
  const baseUrl = serverUrl();
  try {
    const models = await fetchLemonadeModels(baseUrl);
    registerLemonade(pi, baseUrl, models);
  } catch (err) {
    console.error(`[lemonade] Could not reach ${baseUrl}: ${err instanceof Error ? err.message : String(err)}`);
  }
}
