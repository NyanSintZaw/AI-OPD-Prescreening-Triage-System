# Omron BP cuff reader (vendored omblepy)

- Vendored third-party CLI (github userx14/omblepy) reading records from Omron Bluetooth-LE BP monitors via bleak. Treat as upstream code — patch minimally, keep diffable against upstream.
- The backend does NOT import it: `app/services/blood_pressure.py` runs `omblepy.py --jsonOut` as a subprocess and parses the `OMBLEPY_RESULT_JSON` stdout line. Exit code 0 is NOT reliable success — the parser also requires the "communication finished" log line.
- One BLE fetch at a time (module-level asyncio lock in blood_pressure.py); concurrent callers get `busy`. First pairing needs `-p` with the cuff in pairing mode; device model via `-d` (e.g. HEM-7322T), per-model drivers in `deviceSpecific/`.
- Readings feed the booth flow as objective vitals (`turn_context`) and the 15-min crisis rest window (`bp_rest.py`, thresholds >180/>110 pinned to criteria by a drift test).
- Hardware caveat: BLE pairing reliability depends on host bluez version; Jetson/edge boxes stay Ubuntu 22.04.
