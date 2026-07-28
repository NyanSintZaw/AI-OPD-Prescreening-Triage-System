# Omron HBF-222T (VIVA) → Jetson BLE Sync — Integration Guide

This document describes the **working, in-production** Bluetooth sync between an
Omron HBF-222T body composition scale and this machine (NVIDIA Jetson Orin Nano,
Ubuntu 22.04), and defines the **data contract** for building anything on top of
it — e.g. a website/dashboard that shows the patient's latest weight, or an
uploader to Garmin Connect.

**Audience:** a developer or AI agent implementing new features (web UI, API,
uploads). You should NOT need to touch the BLE layer — consume the output files
described in section 3.

---

## 1. System overview

```
 Omron HBF-222T scale                Jetson Orin Nano
 (MAC 28:FF:B2:77:B9:A2)
 ┌──────────────────┐   BLE (bonded/encrypted)  ┌─────────────────────────────┐
 │ patient steps on │ ────advertisement───────▶ │ omscale-sync systemd service │
 │ barefoot, user 1 │ ◀───connect+RACP-read──── │ (runs omscale.py --daemon)   │
 └──────────────────┘                           └──────────┬──────────────────┘
                                                           │ writes
                                                           ▼
                                    omblepy/scale_user1_latest.json  (newest record)
                                    omblepy/scale_user1.csv          (append-only history)
                                    omblepy/omscale_state.json       (sync cursor, internal)
```

- The patient's ONLY action: **step on the scale barefoot with personal number 1**
  (the scale auto-recognizes the person; bare feet are required or the scale
  shows `Err1` and body-fat is not measured — weight still records).
- No button presses, no phone, no cloud. The scale broadcasts automatically
  after each measurement; the always-running daemon hears it, connects, and
  downloads new records.
- **Latency:** measurement → files updated is typically **1–2 minutes**
  (BLE protocol pacing + connection retries). Design UIs accordingly
  (e.g. "waiting for measurement…" state, then refresh).
- The scale buffers up to **30 readings per user** internally, so measurements
  taken while the Jetson is off/unreachable are fetched later, nothing is lost.
  At 30 the oldest is overwritten.

## 2. Components

| Path (relative to `omblepy/`) | Role |
|---|---|
| `omscale.py` | The whole BLE client: scanner, pairing, Omron protocol, record parser, daemon loop. |
| `omscale-sync.service` | systemd unit (installed at `/etc/systemd/system/omscale-sync.service`, enabled). Runs `omscale.py -m 28:FF:B2:77:B9:A2 --daemon` as user `orin_nano`, `Restart=always`. |
| `omscale_state.json` | Sync cursor: scale MAC, last downloaded sequence number per user slot, default user slot. **Internal — do not edit while the service runs.** |
| `scale_user1_latest.json` | **Primary integration point.** Always the single newest measurement for user slot 1. Atomically rewritten after each successful fetch. |
| `scale_user1.csv` | Append-merged history for user slot 1 (deduped by sequence). |
| `README_HBF-222T.md` | This file. |

## 3. Data contract (what a website should consume)

### 3.1 `scale_user1_latest.json` — the newest measurement

```json
{
    "datetime": "2026-07-28 09:08:27",
    "sequence": "17",
    "weight": "67.8",
    "weightUnit": "kg"
}
```

- All values are **strings** (stringified on write).
- `datetime` is the **scale's clock** at the moment the patient stepped on
  (local time, `YYYY-MM-DD HH:MM:SS`). It is NOT the fetch time. See §6 about
  clock resets.
- `sequence` is a monotonically increasing per-user counter assigned by the
  scale. **Use it for change detection:** a new measurement ⇔ `sequence`
  increased. Do not rely on file mtime alone (the file may be rewritten with
  the same record).
- Additional keys appear when the daemon runs with `--full` (currently it does
  not): `bodyFatPercent`, `bmi`, `skeletalMusclePercent`, `visceralFatLevel`,
  `basalMetabolismKcal`, `bodyAgeYears`, `userSlot`. The service currently
  writes the weight-only field set; body fat IS measured and logged in the
  journal — switch the unit's `ExecStart` to include `--full` if the website
  needs body composition, then all fields above land in the JSON/CSV.

### 3.2 `scale_user1.csv` — history

Header (weight-only mode): `datetime,sequence,weight,weightUnit`.
Rows are merged by `sequence` (no duplicates), sorted by datetime. Same
string-format values as the JSON.

### 3.3 Reading the files safely

- Poll the JSON (mtime or 1–5s interval) or use inotify (`IN_CLOSE_WRITE` on
  `scale_user1_latest.json`). Parse errors are transient (rare, small window
  during rewrite) — retry once.
- Treat the `omblepy/` directory as the single source of truth on this host.
  A web backend (e.g. FastAPI) should read these files; it must **never** open
  its own BLE connection to the scale (one BLE client only, see §5).

Minimal example for a web endpoint:

```python
import json, pathlib
LATEST = pathlib.Path("/home/orin_nano/Downloads/omramin/omblepy/scale_user1_latest.json")

def get_latest():
    data = json.loads(LATEST.read_text())
    return {
        "datetime": data["datetime"],
        "sequence": int(data["sequence"]),
        "weightKg": float(data["weight"]),
    }
```

## 4. Service operation

```bash
systemctl status omscale-sync                  # health
journalctl -u omscale-sync -f                  # live log (watch a measurement land)
journalctl -u omscale-sync --since today       # today's activity
sudo systemctl restart omscale-sync            # after editing omscale.py
```

A successful auto-fetch looks like:

```
heard scale advertisement 'BLESmart_0001...' (rssi -71)   ← measurement finished
connected (attempt 3)
consent accepted for user slot 1
device reports 1 stored record(s)
received 1 record(s)
  2026-07-28 09:08:27 seq=17 weight=67.8kg bodyFat=23.7%
latest measurement -> scale_user1_latest.json: 67.8kg at 2026-07-28 09:08:27
```

### Manual CLI (stop the service first — they fight over the adapter)

```bash
sudo systemctl stop omscale-sync
python3 omscale.py -m 28:FF:B2:77:B9:A2 -u 1            # one-shot sync
python3 omscale.py -m 28:FF:B2:77:B9:A2 -u 1 --all      # re-read all 30 stored records
python3 omscale.py -m 28:FF:B2:77:B9:A2 -u 1 -t         # also set the scale's clock
python3 omscale.py -m 28:FF:B2:77:B9:A2 -u 1 --jsonOut  # print records as JSON line (machine-readable: prefix OMSCALE_RESULT_JSON)
python3 omscale.py -p -u 1                              # (re-)register/pair user slot 1 — only after a scale reset
sudo systemctl start omscale-sync
```

## 5. Environment invariants (do not break these)

1. **bluetoothd is a hand-built 5.79 binary** at `/usr/lib/bluetooth/bluetoothd`
   (backup: `bluetoothd.5.64.bak`). Stock Ubuntu 22.04 BlueZ 5.64 has a bug
   where notification subscriptions are never written over the air → the scale
   rejects everything. **An `apt upgrade` of the `bluez` package can silently
   overwrite this binary** — if the scale stops syncing after system updates,
   check `bluetoothd -v` and re-swap.
2. **The BLE bond is permanent** (both sides, user slot 1 registered with
   consent code `0x020E`). Daily syncs need no pairing agent. Re-pairing is
   only needed after `bluetoothctl remove` or a scale communication reset
   ("CLr"), and then requires a NoInputNoOutput agent
   (run `bluetoothctl`, then `agent NoInputNoOutput` + `default-agent`).
3. **Exactly one BLE client.** The daemon owns the adapter. Never run a second
   scanner/connector against the scale in parallel (including the GNOME
   Bluetooth settings panel — keep it closed; its continuous discovery breaks
   LE connections on the Realtek USB adapter).
4. Keep the scale within radio range of the Jetson (observed working at
   rssi −70…−81; weaker than that and the short post-measurement broadcast
   gets missed).

## 6. Device behavior cheat-sheet

| Observation | Meaning |
|---|---|
| Advertises `BLEsmart_…` (lowercase s) | Bluetooth button pressed — explicit transfer/pairing mode. Daemon reacts instantly. |
| Advertises `BLESmart_…` (capital S) | Automatic broadcast right after a measurement / while recently used. **Syncs fine.** Daemon reacts, with a cooldown (60 s → max 15 min) after fruitless attempts so an idle beacon isn't hammered. |
| Display `Err1` | Body-composition measurement failed — patient must be **barefoot** and stay on until body-fat shows. Weight-only record is still stored. NOT a Bluetooth error. |
| Display `o` / SYNC symbol | Untransferred readings in memory; disappears after sync. |
| Records dated ~2023 | Scale clock reset (battery change). Run a sync with `-t` once to set the clock. Battery change ⇒ always re-run `-t`. |
| Personal number wrong on display | Auto-recognition guessed wrong (similar body weights). Patient should select their number with the arrows before/after stepping on. Data lands in whichever slot was confirmed. |

## 7. Protocol internals (only if you must touch the BLE layer)

Implemented in `omscale.py`, mimicking [magcode/omviva](https://github.com/magcode/omviva):

- Requires an **encrypted (bonded) link**; Linux/BlueZ only (macOS CoreBluetooth
  cannot bond this device — verified exhaustively).
- Subscribe ONLY: User Control Point `2a9f`, RACP `2a52`, OmronMeasurementWS
  `8ff2ddfb-4a52-4ce5-85a4-d2f97917792a`. **Subscribing the standard weight-scale
  characteristics (`2a9d`/`2a9c`/`2a99`) makes the scale reject all RACP
  commands with ATT error 0x0E** — do not add them.
- Flow: connect (pair=True) → 1 s settle → subscribe (3 channels) → 2 s →
  UCP consent `02 01 0e 02` → 3 s pacing between writes → RACP count
  `04 03 01 <seq lo> <seq hi>` → RACP read `01 03 01 <seq lo> <seq hi>` →
  records arrive as 19+16-byte chunk pairs on `8ff2ddfb` → RACP `06…`/`10 00`
  ends transfer.
- The post-measurement connection window is short (~5 s if the client stays
  silent) — that is why the settle delays are aggressive.
- Incremental sync = ask only for sequence > `lastSequence` from
  `omscale_state.json`. Delete that key (or use `--all`) to re-download.

## 8. Roadmap / intended next features

- **Website/dashboard** (to be implemented): backend reads
  `scale_user1_latest.json` (+ CSV for history) per §3 and serves it; patient
  measures, page updates within ~2 min. Poll or inotify; no BLE from the web app.
- **Garmin Connect upload**: repo root (`omramin.py`) already authenticates via
  the `garminconnect` library. Plan: a small uploader that tracks its own
  last-uploaded `sequence` and pushes weight/body-fat with the record's
  `datetime` (see `garmin.add_body_composition` / `add_weigh_in`). Reference
  implementation of the same idea: RobertWojtowicz/export2garmin.
