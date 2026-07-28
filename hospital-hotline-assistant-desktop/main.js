const {
  app,
  BrowserWindow,
  Menu,
  Notification,
  Tray,
  ipcMain,
  nativeImage,
  safeStorage,
  screen,
  shell,
} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { shouldNotify, withAuthRetry } = require('./logic');

const APP_ID = 'th.ac.mfu.mch.triage-widget';
const POLL_MS = 30_000;
const WIDTH = 200;
const HEIGHT = 64;

let win = null;
let settingsWin = null;
let tray = null;
let token = null;
let lastCount = -1; // -1 = no successful poll yet; keeps the first poll silent

// ─── config ────────────────────────────────────────────────────────────────
// Plain JSON in the per-user app-data dir. The password is the only secret in
// it and is encrypted separately, so the file itself needs no special handling.

const configPath = () => path.join(app.getPath('userData'), 'config.json');

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(configPath(), 'utf8'));
  } catch {
    return {};
  }
}

function saveConfig(patch) {
  const next = { ...loadConfig(), ...patch };
  fs.writeFileSync(configPath(), JSON.stringify(next, null, 2));
  return next;
}

function getPassword() {
  const { passwordEnc } = loadConfig();
  if (!passwordEnc) return null;
  try {
    return safeStorage.decryptString(Buffer.from(passwordEnc, 'base64'));
  } catch {
    // Encrypted under a different Windows account or a corrupted blob — treat
    // it as "no credentials" so the widget asks for them again.
    return null;
  }
}

// ─── API ───────────────────────────────────────────────────────────────────

function portalUrl() {
  const { serverUrl } = loadConfig();
  return serverUrl ? new URL('/nurse?tab=reviews', serverUrl).toString() : null;
}

/**
 * Behind a reverse proxy the portal and the API share an origin, but they are
 * split in development (:5173 vs :8000) and the web app keeps them separate
 * too (VITE_API_BASE_URL) — so allow an override and fall back to the portal.
 */
function apiBase() {
  const { serverUrl, apiUrl } = loadConfig();
  return apiUrl || serverUrl || null;
}

async function login() {
  const { email } = loadConfig();
  const base = apiBase();
  const password = getPassword();
  if (!base || !email || !password) return false;
  try {
    const res = await fetch(new URL('/admin/login', base), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      token = null;
      return false;
    }
    token = (await res.json()).access_token;
    return true;
  } catch {
    return false; // unreachable server — poll() reports it as offline
  }
}

/** Pending count, or null when we could not authenticate. Throws if offline. */
async function fetchCount() {
  const base = apiBase();
  if (!base) return null;
  const call = () =>
    fetch(new URL('/admin/reviews/pending-count', base), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  const res = await withAuthRetry(call, login);
  if (!res.ok) return null;
  return (await res.json()).pending;
}

// ─── poll loop ─────────────────────────────────────────────────────────────
// Lives in the main process so it keeps running no matter what the renderer is
// doing. Self-rescheduling timeout, so a slow request can never stack up.

function notify(count) {
  const n = new Notification({
    title: 'New triage case',
    body: count === 1 ? '1 case waiting for review' : `${count} cases waiting for review`,
  });
  n.on('click', openPortal);
  n.show();
}

async function poll() {
  let state;
  try {
    const count = await fetchCount();
    if (count === null) {
      state = { status: 'signin' };
    } else {
      if (shouldNotify(lastCount, count)) notify(count);
      lastCount = count;
      state = { status: 'ok', count };
    }
  } catch {
    // Server unreachable. Keep showing the last known number, dimmed, rather
    // than flashing a zero that would read as "queue is clear".
    state = { status: 'offline', count: lastCount < 0 ? 0 : lastCount };
  }
  win?.webContents.send('state', state);
  setTimeout(poll, POLL_MS);
}

// ─── windows ───────────────────────────────────────────────────────────────

function openPortal() {
  const url = portalUrl();
  if (url) shell.openExternal(url);
  else openSettings();
}

function openSettings() {
  if (settingsWin) {
    settingsWin.focus();
    return;
  }
  settingsWin = new BrowserWindow({
    width: 420,
    height: 380,
    title: 'MFU Triage Reviews — Settings',
    resizable: false,
    minimizable: false,
    maximizable: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  settingsWin.setMenuBarVisibility(false);
  settingsWin.loadFile('settings.html');
  settingsWin.on('closed', () => {
    settingsWin = null;
  });
}

function createWidget() {
  const cfg = loadConfig();
  const { workArea } = screen.getPrimaryDisplay();
  win = new BrowserWindow({
    width: WIDTH,
    height: HEIGHT,
    x: cfg.x ?? workArea.x + workArea.width - WIDTH - 24,
    y: cfg.y ?? workArea.y + workArea.height - HEIGHT - 24,
    frame: false,
    transparent: true,
    hasShadow: false, // a transparent window's OS shadow draws as a grey box
    resizable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    fullscreenable: false,
    maximizable: false,
    minimizable: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  });
  // 'screen-saver' is the level that survives other apps going fullscreen.
  win.setAlwaysOnTop(true, 'screen-saver');
  win.setVisibleOnAllWorkspaces(true);
  win.loadFile('widget.html');
  win.on('moved', () => {
    const [x, y] = win.getPosition();
    saveConfig({ x, y });
  });
}

function icon(name) {
  return nativeImage.createFromPath(path.join(__dirname, 'assets', name));
}

function createTray() {
  // Required, not decoration: a frameless widget has no titlebar, so this is
  // the only way to reach settings or quit.
  tray = new Tray(icon('tray.png'));
  tray.setToolTip('MFU Triage Reviews');
  const menu = () =>
    Menu.buildFromTemplate([
      { label: 'Open reviews', click: openPortal },
      { label: 'Settings…', click: openSettings },
      { type: 'separator' },
      {
        label: 'Start with Windows',
        type: 'checkbox',
        checked: app.getLoginItemSettings().openAtLogin,
        click: (item) => {
          app.setLoginItemSettings({ openAtLogin: item.checked });
          tray.setContextMenu(menu());
        },
      },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() },
    ]);
  tray.setContextMenu(menu());
  tray.on('click', openPortal);
}

// ─── IPC ───────────────────────────────────────────────────────────────────

ipcMain.on('open-portal', openPortal);
ipcMain.on('open-settings', openSettings);

ipcMain.handle('get-settings', () => {
  const { serverUrl = '', apiUrl = '', email = '' } = loadConfig();
  // Never hand the password back to a renderer; the field renders empty and
  // blank-means-unchanged on save.
  return { serverUrl, apiUrl, email, hasPassword: Boolean(getPassword()) };
});

ipcMain.handle('save-settings', async (_e, { serverUrl, apiUrl, email, password }) => {
  if (password && !safeStorage.isEncryptionAvailable()) {
    return { ok: false, error: 'OS credential encryption is unavailable on this machine.' };
  }
  const trim = (v) => (v || '').trim().replace(/\/+$/, '');
  const patch = { serverUrl: trim(serverUrl), apiUrl: trim(apiUrl), email };
  if (password) patch.passwordEnc = safeStorage.encryptString(password).toString('base64');
  saveConfig(patch);

  token = null;
  lastCount = -1; // a fresh account starts silent again
  const ok = await login();
  return ok ? { ok: true } : { ok: false, error: 'Could not sign in with those details.' };
});

// ─── lifecycle ─────────────────────────────────────────────────────────────

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', openPortal);

  app.whenReady().then(() => {
    // Windows drops toasts from an app with no AppUserModelID — this must run
    // before the first Notification, and `npm start` has no installer to set it.
    // Under `npm start` the toast header shows this raw id; an installed build
    // shows "MFU Triage Reviews". Keep it identical to build.appId or the
    // installed app's toasts break.
    app.setAppUserModelId(APP_ID);
    createWidget();
    createTray();
    void poll();
    if (!loadConfig().serverUrl) openSettings();
  });

  // Tray app: closing the settings window must not end the process.
  app.on('window-all-closed', () => {});
}
