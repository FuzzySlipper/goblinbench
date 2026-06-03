const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

// ── Contract: parse harness CLI flags ────────────────────────────────────────
const args = process.argv.slice(2);
const testMode = args.includes('--test-mode');
const userDataDirArg = args.find(a => a.startsWith('--user-data-dir='));
const artifactDirArg = args.find(a => a.startsWith('--artifact-dir='));
const artifactDir = artifactDirArg ? artifactDirArg.split('=')[1] : null;

if (userDataDirArg) {
  app.setPath('userData', userDataDirArg.split('=')[1]);
}

// ── Contract: accessibility support ─────────────────────────────────────────
app.accessibilitySupportEnabled = true;

// ── Contract: no telemetry in test mode ─────────────────────────────────────
if (testMode) {
  app.commandLine.appendSwitch('disable-background-networking');
  app.commandLine.appendSwitch('disable-extensions');
}

let mainWindow;

app.whenReady().then(() => {
  mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  mainWindow.loadFile('index.html');

  mainWindow.once('ready-to-show', () => {
    if (!testMode) mainWindow.show();
    // Contract: signal harness readiness
    mainWindow.webContents.send('harness:ready');
    mainWindow.show();
  });

  // Contract: harness reset/seed
  ipcMain.handle('harness:reset', (_event, seed) => {
    mainWindow.webContents.send('app:reset', seed || {});
    return { ok: true };
  });

  // Contract: harness screenshot on demand
  ipcMain.handle('harness:screenshot', async (_event, label) => {
    if (!artifactDir) return { ok: false, reason: 'no artifact-dir' };
    const screenshotsDir = path.join(artifactDir, 'screenshots');
    fs.mkdirSync(screenshotsDir, { recursive: true });
    const filePath = path.join(screenshotsDir, `${label || 'screenshot'}-${Date.now()}.png`);
    const image = await mainWindow.capturePage();
    fs.writeFileSync(filePath, image.toPNG());
    return { ok: true, path: filePath };
  });

  app.on('before-quit', () => {
    writeArtifacts();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

function writeArtifacts() {
  if (!artifactDir) return;
  fs.mkdirSync(artifactDir, { recursive: true });
  const stateDump = {
    closed_at: new Date().toISOString(),
    test_mode: testMode,
    artifact_dir: artifactDir
  };
  fs.writeFileSync(path.join(artifactDir, 'state-dump.json'), JSON.stringify(stateDump, null, 2));
}
