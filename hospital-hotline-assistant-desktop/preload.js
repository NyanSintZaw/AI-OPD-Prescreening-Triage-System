const { contextBridge, ipcRenderer } = require('electron');

// contextIsolation is on and nodeIntegration off — this process holds a staff
// credential, so the renderer gets these five calls and nothing else.
contextBridge.exposeInMainWorld('widget', {
  onState: (cb) => ipcRenderer.on('state', (_e, state) => cb(state)),
  openPortal: () => ipcRenderer.send('open-portal'),
  openSettings: () => ipcRenderer.send('open-settings'),
  getSettings: () => ipcRenderer.invoke('get-settings'),
  saveSettings: (values) => ipcRenderer.invoke('save-settings', values),
});
