import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const PORT = 3000;
const APK_PATH = '/app/applet/app/build/outputs/apk/debug/app-debug.apk';

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);

  if (url.pathname === '/api/health') {
    const apkExists = fs.existsSync(APK_PATH);
    const apkSize = apkExists ? fs.statSync(APK_PATH).size : 0;
    res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ status: 'ok', apkReady: apkExists, apkSizeBytes: apkSize }));
    return;
  }

  if (url.pathname === '/download/harma-ai-debug.apk') {
    if (!fs.existsSync(APK_PATH)) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('APK is still building. Please refresh in a few seconds.');
      return;
    }
    const stat = fs.statSync(APK_PATH);
    res.writeHead(200, {
      'Content-Type': 'application/vnd.android.package-archive',
      'Content-Disposition': 'attachment; filename="harma-ai-debug.apk"',
      'Content-Length': stat.size,
    });
    fs.createReadStream(APK_PATH).pipe(res);
    return;
  }

  const apkExists = fs.existsSync(APK_PATH);
  const apkSizeMb = apkExists ? (fs.statSync(APK_PATH).size / (1024 * 1024)).toFixed(1) : '0.0';

  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(`<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Harma AI — Hands-Free Android Assistant & Accessibility Agent</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background: #090D16; color: #F1F5F9; font-family: system-ui, -apple-system, sans-serif; }
    .orb-glow { box-shadow: 0 0 60px rgba(56, 189, 248, 0.35), inset 0 0 30px rgba(99, 102, 241, 0.4); }
  </style>
</head>
<body class="min-h-screen flex flex-col">
  <header class="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur px-6 py-4 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-sky-500 to-indigo-500 flex items-center justify-center font-bold text-white shadow-lg">H</div>
      <div>
        <h1 class="font-semibold text-base tracking-tight text-white">Harma AI — Android Studio Build & Live Simulator</h1>
        <p class="text-xs text-slate-400">Package: <code class="text-sky-400">com.personal.harmaai</code> • MinSDK 30 • TargetSDK 34</p>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
        ${apkExists ? `APK Ready (${apkSizeMb} MB)` : 'APK Building...'}
      </span>
      <a href="/download/harma-ai-debug.apk" class="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs transition shadow">
        Download Debug APK
      </a>
    </div>
  </header>

  <main class="flex-1 max-w-6xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
    <section class="lg:col-span-5 flex flex-col items-center">
      <div class="w-[340px] rounded-[38px] border-4 border-slate-800 bg-slate-950 p-4 shadow-2xl flex flex-col gap-3">
        <div class="flex items-center justify-between text-[11px] text-slate-400 px-2">
          <span>Harma AI Voice Service</span>
          <span id="netBadge" class="text-emerald-400 font-medium">● ONLINE</span>
        </div>

        <div class="py-5 flex flex-col items-center justify-center bg-slate-900/50 rounded-2xl border border-slate-800/80">
          <div id="orb" class="w-20 h-20 rounded-full bg-gradient-to-br from-sky-400 via-indigo-500 to-purple-600 orb-glow flex items-center justify-center transition-transform duration-300">
            <span class="text-xs font-bold tracking-wider uppercase text-white" id="orbState">IDLE</span>
          </div>
          <p class="mt-3 text-xs text-slate-300 font-medium" id="wakeStatus">Wake Word: "Hey Harma" (ONNX Offline)</p>
          <p class="text-[11px] text-slate-400 mt-0.5" id="sttStatus">STT: Offline SpeechRecognizer + Whisper</p>
        </div>

        <div class="flex gap-2">
          <input id="cmdInput" type="text" value="Hey Harma, play Believer on YouTube"
            class="flex-1 bg-slate-900 border border-slate-700/80 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500"
            placeholder="Say or type a command..." />
          <button onclick="runSimulatedCommand()" class="px-3.5 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs">
            Run
          </button>
        </div>

        <div class="flex items-center justify-between px-1">
          <label class="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input id="offlineToggle" type="checkbox" onchange="toggleOfflineMode()" class="rounded border-slate-700" />
            Simulate Offline Mode (Test Room Task Queue)
          </label>
        </div>

        <div id="stepsLog" class="flex-1 min-h-[210px] max-h-[240px] overflow-y-auto space-y-2 bg-slate-900/70 rounded-xl p-3 border border-slate-800/80 text-xs font-mono">
          <div class="text-slate-400">[System] ScreenParser active (Multi-Window + ElementFingerprint)</div>
          <div class="text-slate-400">[System] Try a preset command on the right or click Run.</div>
        </div>
      </div>
    </section>

    <section class="lg:col-span-7 flex flex-col gap-4">
      <div class="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
        <h2 class="text-sm font-semibold text-white mb-1">Interactive Command Presets (Tier 1 Offline + Tier 2 LLM Loop)</h2>
        <p class="text-xs text-slate-400 mb-3">Click any command below to test how Harma AI routes, perceives `[id]` Set-of-Marks nodes, and verifies completion:</p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <button onclick="setCmd('Hey Harma, turn on flashlight')" class="text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-800/80 border border-slate-800 transition">
            <span class="text-emerald-400 font-semibold">[Tier 1 Offline]</span> "Turn on flashlight"
          </button>
          <button onclick="setCmd('Hey Harma, set an alarm for 7:30 AM')" class="text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-800/80 border border-slate-800 transition">
            <span class="text-emerald-400 font-semibold">[Tier 1 Offline]</span> "Set an alarm for 7:30 AM"
          </button>
          <button onclick="setCmd('Hey Harma, open camera and take a photo')" class="text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-800/80 border border-slate-800 transition">
            <span class="text-sky-400 font-semibold">[Autonomous]</span> "Open camera and take a photo"
          </button>
          <button onclick="setCmd('Hey Harma, play Believer on YouTube')" class="text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-800/80 border border-slate-800 transition">
            <span class="text-purple-400 font-semibold">[Tier 2 / Queue]</span> "Play Believer on YouTube"
          </button>
          <button onclick="setCmd('Hey Harma, send WhatsApp message to Rahul saying I reached home')" class="text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-800/80 border border-slate-800 transition">
            <span class="text-amber-400 font-semibold">[Confirm Gate]</span> "WhatsApp Rahul: I reached home"
          </button>
          <button onclick="setCmd('Hey Harma, open Wi-Fi settings')" class="text-left p-2.5 rounded-xl bg-slate-950/80 hover:bg-slate-800/80 border border-slate-800 transition">
            <span class="text-emerald-400 font-semibold">[Settings Panel]</span> "Open Wi-Fi settings"
          </button>
        </div>
      </div>

      <div class="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 flex-1 flex flex-col">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-white">Live ScreenParser Compact Set-of-Marks Output</h3>
          <span class="text-[11px] text-sky-400 font-mono">ElementResolver + StabilityWaiter</span>
        </div>
        <pre id="parserOutput" class="flex-1 bg-slate-950 rounded-xl p-3.5 text-[11px] font-mono text-slate-300 overflow-x-auto border border-slate-800/90 leading-relaxed">PACKAGE: com.google.android.youtube | ACTIVITY: ShellActivity | TITLE: "YouTube" | KEYBOARD: CLOSED
SCROLL_HINTS: [4] RecyclerView (down)
ELEMENTS (5):
[0] ImageButton desc="Search" id=menu_search clickable bounds=(884,118,980,214)
[1] ImageButton desc="Voice search" id=voice_search clickable bounds=(980,118,1068,214)
[2] ViewGroup "Imagine Dragons - Believer (Official Music Video) • 2.6B views" id=video_item clickable bounds=(0,260,1080,820)
[3] ViewGroup "Believer (Lyrics) • 84M views" id=video_item clickable bounds=(0,824,1080,1380)
[4] RecyclerView id=results scrollable bounds=(0,220,1080,2280)</pre>
      </div>
    </section>
  </main>

  <script>
    const queuedOfflineTasks = [];

    function appendLog(tag, text, color = 'text-slate-300') {
      const box = document.getElementById('stepsLog');
      const div = document.createElement('div');
      div.className = color;
      div.textContent = '[' + tag + '] ' + text;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
    }

    function setCmd(text) {
      document.getElementById('cmdInput').value = text;
      runSimulatedCommand();
    }

    function toggleOfflineMode() {
      const offline = document.getElementById('offlineToggle').checked;
      const badge = document.getElementById('netBadge');
      if (offline) {
        badge.textContent = '● OFFLINE';
        badge.className = 'text-amber-400 font-medium';
        appendLog('NetworkMonitor', 'Connectivity lost — Tier 1 runs offline; Tier 2 queues in Room DB.', 'text-amber-300');
      } else {
        badge.textContent = '● ONLINE';
        badge.className = 'text-emerald-400 font-medium';
        appendLog('NetworkMonitor', 'NET_CAPABILITY_VALIDATED restored.', 'text-emerald-300');
        if (queuedOfflineTasks.length > 0) {
          appendLog('TTS', '"Network is back, continuing your task"', 'text-sky-300');
          while (queuedOfflineTasks.length > 0) {
            const task = queuedOfflineTasks.shift();
            executeOnlineTask(task);
          }
        }
      }
    }

    function executeOnlineTask(clean) {
      appendLog('Observe', 'ScreenParser captured 5 actionable nodes across active windows', 'text-sky-300');
      appendLog('Plan', 'Selected [2] ViewGroup "Imagine Dragons - Believer" (skipped ads/shorts)', 'text-indigo-300');
      appendLog('Act', 'ElementResolver re-resolved fingerprint -> tap(index=2) -> StabilityWaiter settled (210ms)', 'text-emerald-300');
      appendLog('Verify', 'AudioPlayingVerifier confirmed active media playback. Task completed!', 'text-emerald-400');
    }

    function runSimulatedCommand() {
      const raw = document.getElementById('cmdInput').value.trim();
      if (!raw) return;
      const clean = raw.replace(/^hey harma,?\\s*/i, '');
      const offline = document.getElementById('offlineToggle').checked;
      const lower = clean.toLowerCase();

      appendLog('WakeWord', 'Detected "Hey Harma" -> ' + clean, 'text-white font-semibold');

      if (lower.includes('flashlight') || lower.includes('alarm') || lower.includes('wi-fi')) {
        appendLog('Tier 1 FastPath', 'Matched deterministic local intent (0ms LLM, runs offline)', 'text-emerald-300');
        appendLog('Verify', 'System API confirmed state change: ' + clean, 'text-emerald-400');
        return;
      }

      if (lower.includes('camera')) {
        appendLog('Autonomous', 'Launched Camera intent -> dismissed dialog -> tapped shutter [id=1]', 'text-sky-300');
        appendLog('Verify', 'CameraVerifier confirmed new photo in MediaStore.', 'text-emerald-400');
        return;
      }

      if (offline) {
        queuedOfflineTasks.push(clean);
        appendLog('OfflineQueue', 'Saved "' + clean + '" to Room offline_task_queue (status=QUEUED). Toggle Offline Mode off to auto-resume.', 'text-amber-300');
        return;
      }

      executeOnlineTask(clean);
    }
  </script>
</body>
</html>`);
});

server.on('error', (err) => {
  if (err && err.code === 'EADDRINUSE') {
    process.exit(0);
  }
  console.error(err);
  process.exit(1);
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('Harma AI preview server listening on 0.0.0.0:' + PORT);
});
