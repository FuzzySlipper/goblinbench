const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('harness', {
  ready: (cb) => ipcRenderer.on('harness:ready', cb),
  reset: (seed) => ipcRenderer.invoke('harness:reset', seed),
  screenshot: (label) => ipcRenderer.invoke('harness:screenshot', label),
  onReset: (cb) => ipcRenderer.on('app:reset', (_e, seed) => cb(seed))
});
