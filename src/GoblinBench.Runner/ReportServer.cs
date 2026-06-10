using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace GoblinBench.Runner;

/// <summary>
/// Local static-site viewer for run artifacts. Serves a single-page app that browses
/// every run under <c>runs/</c>, compares selected runs in a candidate × scenario grid,
/// and drills down from any cell into the transcript, trace timeline, scorer detail, and
/// raw artifact files — without leaving the page.
///
/// The server is rooted at the repo so the absolute <c>artifact_directory</c> paths in
/// run.json resolve to repo-relative URLs. Read-only; intended for local use only.
/// </summary>
public static class ReportServer
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    // Runs are immutable once written, so cache the parsed ReportData per run directory.
    // Both the catalog and the trend endpoint scan every run; this avoids re-parsing on each request.
    private static readonly ConcurrentDictionary<string, ReportData> RunCache = new();

    private static async Task<ReportData> LoadRunCachedAsync(string runDir)
    {
        if (RunCache.TryGetValue(runDir, out var cached)) return cached;
        var data = await ReportGenerator.LoadRunsAsync(new[] { runDir });
        RunCache[runDir] = data;
        return data;
    }

    public static async Task<int> ServeAsync(string repoRoot, int port, CancellationToken ct)
    {
        repoRoot = Path.GetFullPath(repoRoot);
        var runsRoot = Path.Combine(repoRoot, "runs");
        // Bind all interfaces so the viewer is reachable across the LAN (e.g. over SSH from another box).
        var prefix = $"http://+:{port}/";

        using var listener = new HttpListener();
        listener.Prefixes.Add(prefix);
        try
        {
            listener.Start();
        }
        catch (HttpListenerException ex)
        {
            Console.Error.WriteLine($"Failed to bind {prefix}: {ex.Message}");
            Console.Error.WriteLine($"Try a different port: report serve --port {port + 1}");
            return 1;
        }

        using var reg = ct.Register(() => { try { listener.Stop(); } catch { /* ignore */ } });

        Console.WriteLine("=== GoblinBench Viewer ===");
        Console.WriteLine($"  Serving  {repoRoot}");
        Console.WriteLine($"  Local    http://localhost:{port}/");
        var lan = LocalLanAddress();
        if (lan != null) Console.WriteLine($"  LAN      http://{lan}:{port}/");
        Console.WriteLine("  Bound to all interfaces — anyone on this LAN can reach it.");
        Console.WriteLine("  Press Ctrl+C to stop.");
        Console.WriteLine();

        while (!ct.IsCancellationRequested)
        {
            HttpListenerContext ctx;
            try
            {
                ctx = await listener.GetContextAsync();
            }
            catch (Exception) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (HttpListenerException)
            {
                break;
            }

            _ = Task.Run(async () =>
            {
                try { await HandleAsync(ctx, repoRoot, runsRoot); }
                catch (Exception ex) { TryWriteError(ctx, ex); }
            });
        }

        return 0;
    }

    private static async Task HandleAsync(HttpListenerContext ctx, string repoRoot, string runsRoot)
    {
        var path = Uri.UnescapeDataString(ctx.Request.Url!.AbsolutePath);
        var query = ctx.Request.Url!.Query;

        switch (path)
        {
            case "/" or "/index.html":
                await WriteTextAsync(ctx, ViewerHtml, "text/html; charset=utf-8");
                return;

            case "/catalog.json":
                await WriteTextAsync(ctx, await BuildCatalogJsonAsync(runsRoot), "application/json");
                return;

            case "/report.json":
            {
                var runs = QueryValue(query, "runs");
                if (string.IsNullOrWhiteSpace(runs)) { ctx.Response.StatusCode = 400; ctx.Response.Close(); return; }
                var dirs = runs.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                    .Select(id => Path.Combine(runsRoot, id))
                    .ToList();
                var data = await ReportGenerator.LoadRunsAsync(dirs);
                var json = ReportGenerator.RenderJson(data);
                // Rewrite absolute artifact paths to repo-relative URLs so the browser can fetch them.
                json = json.Replace(repoRoot.Replace('\\', '/') + "/", "")
                           .Replace(repoRoot + Path.DirectorySeparatorChar, "");
                await WriteTextAsync(ctx, json, "application/json");
                return;
            }

            case "/api/files":
            {
                var dir = QueryValue(query, "dir");
                await WriteTextAsync(ctx, ListFilesJson(repoRoot, dir), "application/json");
                return;
            }

            case "/api/trend":
            {
                var scenario = QueryValue(query, "scenario");
                var candidate = QueryValue(query, "candidate");
                if (string.IsNullOrWhiteSpace(scenario) || string.IsNullOrWhiteSpace(candidate))
                { ctx.Response.StatusCode = 400; ctx.Response.Close(); return; }
                await WriteTextAsync(ctx, await BuildTrendJsonAsync(repoRoot, runsRoot, scenario, candidate), "application/json");
                return;
            }

            default:
                await ServeStaticAsync(ctx, repoRoot, path);
                return;
        }
    }

    // ── catalog: one lightweight summary per run ───────────────────────────────

    private static async Task<string> BuildCatalogJsonAsync(string runsRoot)
    {
        var entries = new List<RunCatalogEntry>();
        if (Directory.Exists(runsRoot))
        {
            foreach (var dir in Directory.EnumerateDirectories(runsRoot))
            {
                if (!File.Exists(Path.Combine(dir, "run.json"))) continue;
                try
                {
                    var data = await LoadRunCachedAsync(dir);
                    if (data.RunIds.Count == 0) continue;

                    var suites = data.Scenarios
                        .Select(s => s.ScenarioId.Split('.').First())
                        .Distinct().OrderBy(s => s).ToList();

                    entries.Add(new RunCatalogEntry
                    {
                        RunId = data.RunIds[0],
                        Suites = suites,
                        ScenarioCount = data.Scenarios.Count,
                        Candidates = data.Candidates.Select(c => new CandidatePassSummary
                        {
                            CandidateId = c.CandidateId,
                            Model = c.ModelIdentity?.Model ?? c.CandidateKind,
                            Pass = c.PassCount,
                            Total = c.TotalScenarios
                        }).ToList()
                    });
                }
                catch
                {
                    // Skip unreadable runs rather than failing the whole catalog.
                }
            }
        }

        // Newest first (run IDs are timestamp-prefixed, plus any manual-* dirs).
        entries = entries.OrderByDescending(e => e.RunId).ToList();
        return JsonSerializer.Serialize(entries, JsonOpts);
    }

    // ── trend: one scenario × candidate across every run, in chronological order ─

    private static async Task<string> BuildTrendJsonAsync(
        string repoRoot, string runsRoot, string scenarioId, string candidateId)
    {
        var points = new List<TrendPoint>();
        if (Directory.Exists(runsRoot))
        {
            foreach (var dir in Directory.EnumerateDirectories(runsRoot))
            {
                if (!File.Exists(Path.Combine(dir, "run.json"))) continue;
                try
                {
                    var data = await LoadRunCachedAsync(dir);
                    if (data.RunIds.Count == 0) continue;
                    var scenario = data.Scenarios.FirstOrDefault(s => s.ScenarioId == scenarioId);
                    if (scenario == null || !scenario.CandidateScores.TryGetValue(candidateId, out var entry)) continue;

                    points.Add(new TrendPoint
                    {
                        RunId = data.RunIds[0],
                        Score = entry.Score,
                        Passed = entry.Passed,
                        DurationMs = entry.DurationMs,
                        FailureCategories = entry.FailureCategories,
                        ArtifactDirectory = ToRelative(repoRoot, entry.ArtifactDirectory)
                    });
                }
                catch { /* skip unreadable run */ }
            }
        }

        // Oldest → newest; run IDs are timestamp-prefixed so ordinal sort is chronological.
        points = points.OrderBy(p => p.RunId, StringComparer.Ordinal).ToList();
        return JsonSerializer.Serialize(points, JsonOpts);
    }

    /// <summary>Strip the repoRoot prefix so an absolute artifact path becomes a fetchable URL.</summary>
    private static string? ToRelative(string repoRoot, string? abs)
    {
        if (string.IsNullOrEmpty(abs)) return abs;
        var root = repoRoot.Replace('\\', '/');
        var norm = abs.Replace('\\', '/');
        if (norm.StartsWith(root + "/", StringComparison.Ordinal)) return norm[(root.Length + 1)..];
        return norm;
    }

    private static string? LocalLanAddress()
    {
        try
        {
            // No traffic is sent; connecting a UDP socket just picks the outbound interface.
            using var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, ProtocolType.Udp);
            socket.Connect("8.8.8.8", 65530);
            return (socket.LocalEndPoint as IPEndPoint)?.Address.ToString();
        }
        catch { return null; }
    }

    // ── recursive file listing under a run/candidate dir ───────────────────────

    private static string ListFilesJson(string repoRoot, string? relDir)
    {
        var result = new List<object>();
        if (!string.IsNullOrWhiteSpace(relDir))
        {
            var full = ResolveUnderRoot(repoRoot, relDir);
            if (full != null && Directory.Exists(full))
            {
                foreach (var file in Directory.EnumerateFiles(full, "*", SearchOption.AllDirectories)
                             .OrderBy(f => f, StringComparer.Ordinal))
                {
                    var rel = Path.GetRelativePath(repoRoot, file).Replace('\\', '/');
                    var info = new FileInfo(file);
                    result.Add(new { path = rel, name = Path.GetFileName(file), size = info.Length });
                }
            }
        }
        return JsonSerializer.Serialize(result, JsonOpts);
    }

    // ── static files (read-only, sandboxed to repoRoot) ────────────────────────

    private static async Task ServeStaticAsync(HttpListenerContext ctx, string repoRoot, string path)
    {
        var rel = path.TrimStart('/');
        var full = ResolveUnderRoot(repoRoot, rel);
        if (full == null || !File.Exists(full))
        {
            ctx.Response.StatusCode = 404;
            await WriteTextAsync(ctx, "not found", "text/plain");
            return;
        }

        ctx.Response.ContentType = ContentTypeFor(full);
        ctx.Response.StatusCode = 200;
        await using var fs = File.OpenRead(full);
        await fs.CopyToAsync(ctx.Response.OutputStream);
        ctx.Response.Close();
    }

    /// <summary>Resolve a relative path under repoRoot, refusing anything that escapes it.</summary>
    private static string? ResolveUnderRoot(string repoRoot, string rel)
    {
        if (string.IsNullOrEmpty(rel)) return null;
        var full = Path.GetFullPath(Path.Combine(repoRoot, rel));
        var rootWithSep = repoRoot.EndsWith(Path.DirectorySeparatorChar)
            ? repoRoot : repoRoot + Path.DirectorySeparatorChar;
        return full.StartsWith(rootWithSep, StringComparison.Ordinal) || full == repoRoot ? full : null;
    }

    private static string ContentTypeFor(string path) => Path.GetExtension(path).ToLowerInvariant() switch
    {
        ".html" => "text/html; charset=utf-8",
        ".json" => "application/json",
        ".jsonl" or ".txt" or ".md" or ".log" => "text/plain; charset=utf-8",
        ".js" => "text/javascript",
        ".css" => "text/css",
        ".png" => "image/png",
        ".jpg" or ".jpeg" => "image/jpeg",
        ".svg" => "image/svg+xml",
        _ => "application/octet-stream"
    };

    // ── helpers ────────────────────────────────────────────────────────────────

    private static string? QueryValue(string query, string key)
    {
        if (string.IsNullOrEmpty(query)) return null;
        foreach (var pair in query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var eq = pair.IndexOf('=');
            if (eq < 0) continue;
            if (Uri.UnescapeDataString(pair[..eq]) == key)
                return Uri.UnescapeDataString(pair[(eq + 1)..]);
        }
        return null;
    }

    private static async Task WriteTextAsync(HttpListenerContext ctx, string body, string contentType)
    {
        var bytes = Encoding.UTF8.GetBytes(body);
        ctx.Response.ContentType = contentType;
        ctx.Response.ContentLength64 = bytes.Length;
        await ctx.Response.OutputStream.WriteAsync(bytes);
        ctx.Response.Close();
    }

    private static void TryWriteError(HttpListenerContext ctx, Exception ex)
    {
        try
        {
            ctx.Response.StatusCode = 500;
            var bytes = Encoding.UTF8.GetBytes("error: " + ex.Message);
            ctx.Response.OutputStream.Write(bytes);
            ctx.Response.Close();
        }
        catch { /* connection already gone */ }
    }

    private sealed class RunCatalogEntry
    {
        [JsonPropertyName("run_id")] public string RunId { get; init; } = "";
        [JsonPropertyName("suites")] public List<string> Suites { get; init; } = new();
        [JsonPropertyName("scenario_count")] public int ScenarioCount { get; init; }
        [JsonPropertyName("candidates")] public List<CandidatePassSummary> Candidates { get; init; } = new();
    }

    private sealed class CandidatePassSummary
    {
        [JsonPropertyName("candidate_id")] public string CandidateId { get; init; } = "";
        [JsonPropertyName("model")] public string? Model { get; init; }
        [JsonPropertyName("pass")] public int Pass { get; init; }
        [JsonPropertyName("total")] public int Total { get; init; }
    }

    private sealed class TrendPoint
    {
        [JsonPropertyName("run_id")] public string RunId { get; init; } = "";
        [JsonPropertyName("score")] public double? Score { get; init; }
        [JsonPropertyName("passed")] public bool? Passed { get; init; }
        [JsonPropertyName("duration_ms")] public long DurationMs { get; init; }
        [JsonPropertyName("failure_categories")] public List<string> FailureCategories { get; init; } = new();
        [JsonPropertyName("artifact_directory")] public string? ArtifactDirectory { get; init; }
    }

    // ── the single-page viewer ─────────────────────────────────────────────────

    private const string ViewerHtml = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GoblinBench Viewer</title>
<style>
:root{color-scheme:dark;--bg:#101014;--panel:#181923;--panel2:#202231;--muted:#9aa4b2;--text:#eff3ff;--line:#313442;--good:#50d890;--bad:#ff6b7a;--mid:#ffd166;--chip:#25283a;--accent:#8bd3ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:14px;position:sticky;top:0;background:var(--bg);z-index:5}
header h1{font-size:18px;margin:0}
header .muted{color:var(--muted);font-size:13px}
.layout{display:flex;min-height:calc(100vh - 50px)}
.sidebar{width:360px;flex:none;border-right:1px solid var(--line);padding:12px;overflow:auto;max-height:calc(100vh - 50px);position:sticky;top:50px}
.main{flex:1;padding:16px 18px;overflow:auto}
.muted{color:var(--muted)}
input,select,button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:7px 9px;font:inherit}
button{cursor:pointer}
button.primary{background:var(--accent);color:#06223a;border-color:var(--accent);font-weight:600}
button:disabled{opacity:.5;cursor:default}
.runrow{border:1px solid var(--line);border-radius:10px;padding:9px;margin:7px 0;background:var(--panel);cursor:pointer}
.runrow:hover{background:var(--panel2)}
.runrow.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.runrow .rid{font-size:12px;color:var(--accent);word-break:break-all}
.chip{display:inline-block;background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin:2px 3px 0 0;color:#d8def0;font-size:11px}
.bar{display:inline-block;height:6px;border-radius:3px;background:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{border-bottom:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:var(--panel2);position:sticky;top:0}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:var(--panel2)}
.pass{color:var(--good);font-weight:700}.fail{color:var(--bad);font-weight:700}.maybe{color:var(--mid);font-weight:700}
.cat{border-color:#68424a;background:#2a1b24;color:#ffb3bf}
td.reg{background:#2a1620}td.imp{background:#13251b}td.new{background:#13202e}td.removed{background:#1c1c22}
.delta{font-size:11px;color:var(--muted)}
.pill{display:inline-block;border-radius:6px;padding:1px 6px;font-size:11px;font-weight:600}
.pill.reg{background:#3a1620;color:#ff9bab}.pill.imp{background:#16321f;color:#7ee2a8}.pill.new{background:#16273a;color:#9fd4ff}.pill.removed{background:#26262e;color:#aab}
.toolbar{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
/* drawer */
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none;z-index:9}
.scrim.open{display:block}
.drawer{position:fixed;top:0;right:0;height:100vh;width:min(820px,94vw);background:var(--bg);border-left:1px solid var(--line);transform:translateX(100%);transition:transform .18s ease;z-index:10;display:flex;flex-direction:column}
.drawer.open{transform:translateX(0)}
.drawer .dh{padding:14px 16px;border-bottom:1px solid var(--line)}
.drawer .tabs{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.drawer .tabs button{border-radius:999px;padding:5px 12px}
.drawer .tabs button.active{background:var(--accent);color:#06223a;border-color:var(--accent)}
.drawer .body{padding:14px 16px;overflow:auto;flex:1}
.close{margin-left:auto}
.msg{border:1px solid var(--line);border-radius:10px;padding:9px 11px;margin:9px 0;background:var(--panel)}
.msg .role{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px}
.msg.system{border-color:#3a3a52}.msg.user{border-color:#33485b}.msg.assistant{border-color:#2f5d44}.msg.tool{border-color:#5a4a2a}
.tcall{background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:7px 9px;margin:6px 0}
.tcall .tn{color:var(--accent);font-weight:600}
pre{white-space:pre-wrap;word-break:break-word;background:#0c0d12;border:1px solid var(--line);border-radius:8px;padding:9px;margin:5px 0;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;max-height:none}
.ev{border-left:2px solid var(--line);padding:4px 0 4px 10px;margin:3px 0}
.ev .en{color:var(--accent);font-weight:600;font-size:12px}
.ev .ts{color:var(--muted);font-size:11px}
.scard{border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin:8px 0;background:var(--panel)}
.flist a{display:block;color:var(--accent);padding:3px 0;text-decoration:none;font:12px/1.5 ui-monospace,monospace}
.flist a:hover{text-decoration:underline}
.empty{color:var(--muted);padding:30px;text-align:center}
a{color:var(--accent)}
</style>
</head>
<body>
<header>
  <h1>🟢 GoblinBench Viewer</h1>
  <span class="muted" id="status">loading runs…</span>
</header>
<div class="layout">
  <div class="sidebar">
    <input id="runFilter" placeholder="filter runs (id / suite / candidate)…" style="width:100%" oninput="renderRuns()">
    <div style="margin-top:8px" class="toolbar">
      <button class="primary" id="openBtn" onclick="openGrid()" disabled>Open grid</button>
      <button onclick="clearSel()">Clear</button>
    </div>
    <div id="runList"></div>
  </div>
  <div class="main" id="main">
    <div class="empty">Select one or more runs on the left, then <b>Open grid</b>.<br>
    Pick several runs to compare the same scenarios side by side.</div>
  </div>
</div>

<div class="scrim" id="scrim" onclick="closeDrawer()"></div>
<aside class="drawer" id="drawer">
  <div class="dh">
    <div style="display:flex;align-items:center;gap:10px">
      <div>
        <div id="dTitle" style="font-weight:600"></div>
        <div class="muted" id="dSub" style="font-size:12px"></div>
      </div>
      <button class="close" onclick="closeDrawer()">✕ Close</button>
    </div>
  </div>
  <div class="tabs" id="dTabs"></div>
  <div class="body" id="dBody"></div>
</aside>

<script>
let CATALOG=[], SELECTED=new Set(), REPORT=null;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

async function init(){
  try{
    CATALOG=await (await fetch('catalog.json')).json();
    document.getElementById('status').textContent=CATALOG.length+' runs';
    renderRuns();
  }catch(e){ document.getElementById('status').textContent='failed to load catalog: '+e; }
}

function renderRuns(){
  const q=document.getElementById('runFilter').value.toLowerCase();
  const list=document.getElementById('runList');
  list.innerHTML='';
  for(const r of CATALOG){
    const hay=(r.run_id+' '+(r.suites||[]).join(' ')+' '+(r.candidates||[]).map(c=>c.candidate_id+' '+(c.model||'')).join(' ')).toLowerCase();
    if(q && !hay.includes(q)) continue;
    const div=document.createElement('div');
    div.className='runrow'+(SELECTED.has(r.run_id)?' sel':'');
    const cands=(r.candidates||[]).map(c=>{
      const pct=c.total? Math.round(100*c.pass/c.total):0;
      return `<span class="chip">${esc(c.candidate_id)} ${c.pass}/${c.total}</span>`;
    }).join('');
    div.innerHTML=`<div class="rid">${esc(r.run_id)}</div>
      <div style="margin-top:3px">${(r.suites||[]).map(s=>`<span class="chip">${esc(s)}</span>`).join('')}</div>
      <div class="muted" style="font-size:12px;margin-top:3px">${r.scenario_count} scenarios</div>
      <div style="margin-top:3px">${cands}</div>`;
    div.onclick=()=>{ SELECTED.has(r.run_id)?SELECTED.delete(r.run_id):SELECTED.add(r.run_id); renderRuns(); syncToolbar(); };
    list.appendChild(div);
  }
}
function syncToolbar(){ document.getElementById('openBtn').disabled=SELECTED.size===0; }
function clearSel(){ SELECTED.clear(); renderRuns(); syncToolbar(); }

async function openGrid(){
  const ids=[...SELECTED];
  const main=document.getElementById('main');
  main.innerHTML='<div class="empty">loading…</div>';
  REPORT=await (await fetch('report.json?runs='+encodeURIComponent(ids.join(',')))).json();
  renderGrid();
}

function primaryEntry(score){
  if(!score) return null;
  const d=score.scorer_details||[];
  return d.find(s=>s.passed!=null && s.scorer_id!=='noop' && s.scorer_id!=='latency') || d[0] || null;
}

function renderGrid(){
  const main=document.getElementById('main');
  const cands=REPORT.candidates||[], scenarios=REPORT.scenarios||[];
  const runIds=REPORT.run_ids||[];
  let h=`<div class="toolbar">
     <b>${scenarios.length}</b> scenarios × <b>${cands.length}</b> candidates &nbsp;·&nbsp; runs: ${runIds.map(esc).join(', ')}
     <span style="margin-left:auto"></span>
     ${runIds.length>=2?'<button onclick="enterDiff()">⇄ Diff runs</button>':''}
     <label class="muted"><input type="checkbox" id="failOnly" onchange="renderGrid()"> failures only</label>
   </div>`;
  h+='<table><thead><tr><th>Scenario</th>';
  for(const c of cands) h+=`<th>${esc(c.candidate_id)}<div class="muted" style="font-weight:400">${esc(c.model_identity?c.model_identity.model:c.candidate_kind)}</div></th>`;
  h+='</tr></thead><tbody>';
  const failOnly=document.getElementById('failOnly')?.checked;
  for(const s of scenarios){
    const cells=cands.map(c=>{
      const score=s.candidate_scores?s.candidate_scores[c.candidate_id]:null;
      if(!score) return {html:'<td class="muted">—</td>',fail:false};
      const p=primaryEntry(score);
      const passed=score.passed===true?'pass':score.passed===false?'fail':'maybe';
      const icon=passed==='pass'?'✓':passed==='fail'?'✗':'~';
      const sc=score.score!=null?score.score.toFixed(2):'';
      const lat=score.duration_ms<1000?score.duration_ms+'ms':(score.duration_ms/1000).toFixed(1)+'s';
      const cats=(score.failure_categories||[]).map(x=>`<span class="chip cat">${esc(x)}</span>`).join('');
      const td=`<td class="clickable" onclick='openDrawer(${JSON.stringify(s.scenario_id)},${JSON.stringify(c.candidate_id)})'>
          <span class="${passed}">${icon} ${sc}</span> <span class="muted">${lat}</span><div>${cats}</div></td>`;
      return {html:td,fail:passed==='fail'};
    });
    if(failOnly && !cells.some(c=>c.fail)) continue;
    const shortId=s.scenario_id.includes('.')?s.scenario_id.slice(s.scenario_id.indexOf('.')+1):s.scenario_id;
    h+=`<tr><td><div>${esc(shortId)}</div><div class="muted" style="font-size:11px">${esc(s.scenario_id.split('.')[0])}</div></td>${cells.map(c=>c.html).join('')}</tr>`;
  }
  h+='</tbody></table>';
  main.innerHTML=h;
}

// ── diff: baseline vs target run ────────────────────────────────────
let DIFF={reports:{}};
async function ensureReport(runId){
  if(DIFF.reports[runId]) return DIFF.reports[runId];
  const d=await (await fetch('report.json?runs='+encodeURIComponent(runId))).json();
  DIFF.reports[runId]=d; return d;
}
function entryFor(runId,sid,cid){
  const d=DIFF.reports[runId]; if(!d) return null;
  const s=(d.scenarios||[]).find(x=>x.scenario_id===sid);
  return s&&s.candidate_scores?s.candidate_scores[cid]||null:null;
}
function diffClass(b,t){
  if(b&&!t) return 'removed';
  if(!b&&t) return 'new';
  if(!b&&!t) return 'gap';
  if(b.passed===true&&t.passed===false) return 'reg';
  if(b.passed===false&&t.passed===true) return 'imp';
  if(b.score!=null&&t.score!=null){ if(t.score-b.score<=-0.005) return 'reg'; if(t.score-b.score>=0.005) return 'imp'; }
  return 'same';
}
async function enterDiff(){
  const runIds=REPORT.run_ids||[];
  DIFF.baseline=runIds[0]; DIFF.target=runIds[runIds.length-1];
  await Promise.all(runIds.map(ensureReport));
  renderDiff();
}
function exitDiff(){ renderGrid(); }

function renderDiff(){
  const main=document.getElementById('main');
  const runIds=REPORT.run_ids||[];
  const opt=(sel)=>runIds.map(r=>`<option value="${esc(r)}"${r===sel?' selected':''}>${esc(r)}</option>`).join('');
  const bRep=DIFF.reports[DIFF.baseline], tRep=DIFF.reports[DIFF.target];
  // union of scenarios and candidates across the two runs
  const sids=[...new Set([...(bRep.scenarios||[]),...(tRep.scenarios||[])].map(s=>s.scenario_id))];
  const cids=[...new Set([...(bRep.candidates||[]),...(tRep.candidates||[])].map(c=>c.candidate_id))];

  let reg=0,imp=0;
  for(const sid of sids) for(const cid of cids){
    const cl=diffClass(entryFor(DIFF.baseline,sid,cid),entryFor(DIFF.target,sid,cid));
    if(cl==='reg')reg++; if(cl==='imp')imp++;
  }

  let h=`<div class="toolbar">
     <button onclick="exitDiff()">← Back to grid</button>
     <label class="muted">baseline <select onchange="DIFF.baseline=this.value;renderDiff()">${opt(DIFF.baseline)}</select></label>
     <span class="muted">→</span>
     <label class="muted">target <select onchange="DIFF.target=this.value;renderDiff()">${opt(DIFF.target)}</select></label>
     <span class="pill reg">${reg} regressions</span> <span class="pill imp">${imp} improvements</span>
     <span style="margin-left:auto"></span>
     <label class="muted"><input type="checkbox" id="changesOnly" checked onchange="renderDiff()"> changes only</label>
   </div>`;
  const changesOnly=document.getElementById('changesOnly')?document.getElementById('changesOnly').checked:true;
  h+='<table><thead><tr><th>Scenario</th>'+cids.map(c=>`<th>${esc(c)}</th>`).join('')+'</tr></thead><tbody>';
  for(const sid of sids){
    const cells=cids.map(cid=>{
      const b=entryFor(DIFF.baseline,sid,cid), t=entryFor(DIFF.target,sid,cid);
      const cl=diffClass(b,t);
      if(cl==='gap') return {html:'<td class="muted">—</td>',changed:false};
      const fmt=e=>e? (e.passed===true?'✓':e.passed===false?'✗':'~')+(e.score!=null?' '+e.score.toFixed(2):'') : '—';
      let inner;
      if(cl==='new') inner=`<span class="pill new">new</span> ${fmt(t)}`;
      else if(cl==='removed') inner=`<span class="pill removed">gone</span> ${fmt(b)}`;
      else{
        const delta=(b.score!=null&&t.score!=null)?(t.score-b.score):null;
        const ds=delta!=null?`<span class="delta">${delta>=0?'+':''}${delta.toFixed(2)}</span>`:'';
        inner=`<span class="muted">${fmt(b)}</span> → ${fmt(t)} ${ds}`;
      }
      const td=`<td class="${cl} clickable" onclick='openDiffCell(${JSON.stringify(sid)},${JSON.stringify(cid)})'>${inner}</td>`;
      return {html:td,changed:cl==='reg'||cl==='imp'||cl==='new'||cl==='removed'};
    });
    if(changesOnly && !cells.some(c=>c.changed)) continue;
    const shortId=sid.includes('.')?sid.slice(sid.indexOf('.')+1):sid;
    h+=`<tr><td><div>${esc(shortId)}</div><div class="muted" style="font-size:11px">${esc(sid.split('.')[0])}</div></td>${cells.map(c=>c.html).join('')}</tr>`;
  }
  h+='</tbody></table>';
  main.innerHTML=h;
}
// open the target run's artifacts (fall back to baseline) for a diff cell
function openDiffCell(sid,cid){
  const t=entryFor(DIFF.target,sid,cid)||entryFor(DIFF.baseline,sid,cid);
  if(t) openDrawer(sid,cid,t);
}

// ── drawer / drill-down ─────────────────────────────────────────────
let DRAWER={};
function findScore(sid,cid){
  const s=(REPORT.scenarios||[]).find(x=>x.scenario_id===sid);
  return s? s.candidate_scores[cid] : null;
}
function openDrawer(sid,cid,override){
  const score=override||findScore(sid,cid);
  if(!score) return;
  const artDir=score.artifact_directory||'';            // runs/.../candidates/<c>/artifacts
  const candDir=artDir.replace(/\/artifacts\/?$/,'');    // runs/.../candidates/<c>
  const runId=score.run_id||(candDir.split('/')[1]||''); // runs/<runId>/...
  DRAWER={sid,cid,score,artDir,candDir,runId,tab:'transcript'};
  const passed=score.passed===true?'pass':score.passed===false?'fail':'maybe';
  document.getElementById('dTitle').innerHTML=`<span class="${passed}">${passed==='pass'?'✓':passed==='fail'?'✗':'~'}</span> ${esc(sid)}`;
  document.getElementById('dSub').textContent=cid+' · '+esc(runId)+' · score '+(score.score!=null?score.score.toFixed(3):'—')+' · '+(score.duration_ms)+'ms';
  const tabs=document.getElementById('dTabs');
  tabs.innerHTML=['transcript','trace','scores','files','trend'].map(t=>`<button data-t="${t}" onclick="selTab('${t}')">${t}</button>`).join('');
  document.getElementById('scrim').classList.add('open');
  document.getElementById('drawer').classList.add('open');
  selTab('transcript');
}
function closeDrawer(){ document.getElementById('scrim').classList.remove('open'); document.getElementById('drawer').classList.remove('open'); }
function selTab(t){
  DRAWER.tab=t;
  for(const b of document.querySelectorAll('#dTabs button')) b.classList.toggle('active',b.dataset.t===t);
  const body=document.getElementById('dBody');
  body.innerHTML='<div class="muted">loading…</div>';
  if(t==='transcript') renderTranscript(body);
  else if(t==='trace') renderTrace(body);
  else if(t==='scores') renderScores(body);
  else if(t==='files') renderFiles(body);
  else if(t==='trend') renderTrend(body);
}

async function fetchText(rel){ const r=await fetch(rel); if(!r.ok) throw new Error(r.status+' '+rel); return r.text(); }
async function fetchJson(rel){ return JSON.parse(await fetchText(rel)); }
// Split a stream of concatenated JSON values (handles pretty-printed .jsonl).
function splitJsonStream(text){
  const out=[]; let depth=0,start=-1,inStr=false,escp=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];
    if(inStr){ if(escp)escp=false; else if(ch==='\\')escp=true; else if(ch==='"')inStr=false; continue; }
    if(ch==='"'){inStr=true; if(depth===0&&start<0)start=i; continue;}
    if(ch==='{'||ch==='['){ if(depth===0)start=i; depth++; }
    else if(ch==='}'||ch===']'){ depth--; if(depth===0&&start>=0){ try{out.push(JSON.parse(text.slice(start,i+1)));}catch(e){} start=-1; } }
  }
  return out;
}

async function renderTranscript(body){
  const tries=[DRAWER.artDir+'/chat_transcript.json',DRAWER.artDir+'/session_transcript.json'];
  let msgs=null;
  for(const u of tries){ try{ msgs=await fetchJson(u); break; }catch(e){} }
  if(!msgs){ body.innerHTML='<div class="empty">No transcript artifact found.</div>'; return; }
  if(!Array.isArray(msgs)) msgs=msgs.messages||[];
  body.innerHTML=msgs.map(m=>{
    const role=(m.role||'?');
    let inner=m.content?`<div>${esc(typeof m.content==='string'?m.content:JSON.stringify(m.content))}</div>`:'';
    if(m.tool_calls) inner+=m.tool_calls.map(tc=>{
      const fn=tc.function||tc;
      return `<div class="tcall"><span class="tn">⚙ ${esc(fn.name)}</span><pre>${esc(fn.arguments||'')}</pre></div>`;
    }).join('');
    if(role==='tool') inner=`<pre>${esc(typeof m.content==='string'?m.content:JSON.stringify(m.content,null,2))}</pre>`;
    return `<div class="msg ${esc(role)}"><div class="role">${esc(role)}${m.name?' · '+esc(m.name):''}</div>${inner}</div>`;
  }).join('');
}

async function renderTrace(body){
  try{
    const text=await fetchText(DRAWER.candDir+'/trace.jsonl');
    const events=splitJsonStream(text);
    if(!events.length){ body.innerHTML='<div class="empty">Trace empty.</div>'; return; }
    body.innerHTML=events.map(e=>{
      const data=e.data?`<pre>${esc(JSON.stringify(e.data,null,2))}</pre>`:'';
      const ts=e.timestamp?e.timestamp.split('T')[1]||e.timestamp:'';
      return `<div class="ev"><span class="en">${esc(e.event||'event')}</span> <span class="ts">${esc(ts)}</span>${data}</div>`;
    }).join('');
  }catch(e){ body.innerHTML='<div class="empty">No trace.jsonl found.</div>'; }
}

async function renderScores(body){
  let scores=null;
  try{ scores=await fetchJson(DRAWER.candDir+'/scores.json'); }
  catch(e){ scores=DRAWER.score.scorer_details; }
  if(!scores||!scores.length){ body.innerHTML='<div class="empty">No scores.</div>'; return; }
  body.innerHTML=scores.map(s=>{
    const passed=s.passed===true?'pass':s.passed===false?'fail':'maybe';
    const detail=s.detail?`<details><summary class="muted">detail</summary><pre>${esc(JSON.stringify(s.detail,null,2))}</pre></details>`:'';
    return `<div class="scard"><div><span class="${passed}">${passed==='pass'?'✓':passed==='fail'?'✗':'~'}</span>
      <b>${esc(s.scorer_id||s.scorer_name)}</b> <span class="muted">${s.score!=null?s.score.toFixed(3):''}</span></div>
      <div class="muted" style="margin:3px 0">${esc(s.human_summary||s.explanation||s.error||'')}</div>${detail}</div>`;
  }).join('');
}

async function renderFiles(body){
  try{
    const files=await fetchJson('api/files?dir='+encodeURIComponent(DRAWER.candDir));
    if(!files.length){ body.innerHTML='<div class="empty">No files.</div>'; return; }
    body.innerHTML='<div class="flist">'+files.map(f=>{
      const kb=(f.size/1024).toFixed(1);
      const sub=f.path.slice(DRAWER.candDir.length+1);
      return `<a href="${esc(f.path)}" target="_blank">${esc(sub)} <span class="muted">(${kb} KB)</span></a>`;
    }).join('')+'</div>';
  }catch(e){ body.innerHTML='<div class="empty">Could not list files.</div>'; }
}

// Parse the timestamp embedded in a run id: run-YYYYMMDD-HHMMSS-hash
function runDateLabel(runId){
  const m=/^run-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(runId||'');
  return m? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : runId;
}

async function renderTrend(body){
  let pts;
  try{ pts=await fetchJson('api/trend?scenario='+encodeURIComponent(DRAWER.sid)+'&candidate='+encodeURIComponent(DRAWER.cid)); }
  catch(e){ body.innerHTML='<div class="empty">Trend lookup failed.</div>'; return; }
  if(!pts.length){ body.innerHTML='<div class="empty">No history for this scenario × candidate.</div>'; return; }

  const n=pts.length, W=Math.max(360,n*38), H=200, padL=34,padR=14,padT=14,padB=30;
  const plotW=W-padL-padR, plotH=H-padT-padB;
  const x=i=> padL+(n===1? plotW/2 : i*plotW/(n-1));
  const y=s=> padT+(1-Math.max(0,Math.min(1,s)))*plotH;
  const color=p=> p.passed===true?'#50d890':p.passed===false?'#ff6b7a':'#ffd166';

  // line through points that have a numeric score
  let path='';
  pts.forEach((p,i)=>{ if(p.score==null) return; path+=(path?' L':'M')+x(i).toFixed(1)+' '+y(p.score).toFixed(1); });

  let svg=`<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">`;
  // gridlines 0 / 0.5 / 1
  [0,0.5,1].forEach(g=>{ const yy=y(g).toFixed(1);
    svg+=`<line x1="${padL}" y1="${yy}" x2="${W-padR}" y2="${yy}" stroke="#313442"/>`;
    svg+=`<text x="4" y="${(+yy+4).toFixed(1)}" fill="#9aa4b2" font-size="10">${g}</text>`; });
  if(path) svg+=`<path d="${path}" fill="none" stroke="#8bd3ff" stroke-width="1.5"/>`;
  pts.forEach((p,i)=>{
    const cy= p.score==null? y(0): y(p.score);
    const hollow= p.score==null;
    svg+=`<circle cx="${x(i).toFixed(1)}" cy="${cy.toFixed(1)}" r="5"
       fill="${hollow?'#101014':color(p)}" stroke="${color(p)}" stroke-width="2"
       style="cursor:pointer" onclick='openTrendPoint(${i})'>
       <title>${esc(runDateLabel(p.run_id))} · ${p.score!=null?p.score.toFixed(3):'no score'} · ${p.passed===true?'pass':p.passed===false?'fail':'—'}</title></circle>`;
  });
  svg+='</svg>';

  const rows=pts.map((p,i)=>{
    const passed=p.passed===true?'pass':p.passed===false?'fail':'maybe';
    const cats=(p.failure_categories||[]).map(c=>`<span class="chip cat">${esc(c)}</span>`).join('');
    const cur=p.run_id===DRAWER.runId?' style="outline:1px solid var(--accent)"':'';
    return `<tr class="clickable"${cur} onclick='openTrendPoint(${i})'>
      <td class="muted" style="font-size:12px">${esc(runDateLabel(p.run_id))}</td>
      <td><span class="${passed}">${passed==='pass'?'✓':passed==='fail'?'✗':'~'}</span> ${p.score!=null?p.score.toFixed(3):'—'}</td>
      <td>${cats}</td></tr>`;
  }).join('');

  TREND=pts;
  body.innerHTML=`<div class="muted" style="margin-bottom:6px">${n} run(s) · score over time (click a point to open that run)</div>
    ${svg}
    <table style="margin-top:10px"><thead><tr><th>Run</th><th>Score</th><th>Failure categories</th></tr></thead><tbody>${rows}</tbody></table>`;
}
let TREND=[];
function openTrendPoint(i){ const p=TREND[i]; if(p) openDrawer(DRAWER.sid,DRAWER.cid,p); }

document.addEventListener('keydown',e=>{ if(e.key==='Escape') closeDrawer(); });
init();
</script>
</body>
</html>
""";
}
