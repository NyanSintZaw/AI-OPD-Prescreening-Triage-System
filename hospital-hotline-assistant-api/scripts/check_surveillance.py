"""Quick diagnostic: check disease_surveillance and related classification data."""
import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:5432/hospital_hotline"
    )

    print("=== disease_surveillance rows ===")
    ds_rows = await conn.fetch(
        "SELECT id, session_id, symptom_keywords, symptoms_summary, "
        "severity_level, location_area, reported_at "
        "FROM disease_surveillance ORDER BY reported_at DESC LIMIT 20"
    )
    if not ds_rows:
        print("  (empty)")
    for r in ds_rows:
        print("  session : " + str(r["session_id"])[:8] + "...")
        print("  keywords: " + str(r["symptom_keywords"]))
        print("  summary : " + str(r["symptoms_summary"]))
        print("  severity: " + str(r["severity_level"]))
        print("  location: " + str(r["location_area"]))
        print("  time    : " + str(r["reported_at"]))
        print()

    print("=== Recent sessions ===")
    sessions = await conn.fetch(
        "SELECT id, status, started_at FROM sessions ORDER BY started_at DESC LIMIT 5"
    )
    for s in sessions:
        print("  " + str(s["id"])[:8] + "...  status=" + str(s["status"]) + "  started=" + str(s["started_at"]))

    print()
    print("=== Recent severity_assessments ===")
    sa_rows = await conn.fetch(
        "SELECT session_id, severity, confidence, explanation, created_at "
        "FROM severity_assessments ORDER BY created_at DESC LIMIT 10"
    )
    if not sa_rows:
        print("  (no assessments yet)")
    for r in sa_rows:
        print(
            "  session=" + str(r["session_id"])[:8]
            + " severity=" + str(r["severity"])
            + " conf=" + str(r["confidence"])
        )
        print("  explanation: " + str(r["explanation"]))

    print()
    print("=== triage_classification in session metadata ===")
    meta_rows = await conn.fetch(
        "SELECT id, metadata FROM sessions "
        "WHERE (metadata->>'triage_classification') IS NOT NULL "
        "ORDER BY started_at DESC LIMIT 5"
    )
    if not meta_rows:
        print("  (no classified sessions yet)")
    for m in meta_rows:
        import json as _json
        raw = m["metadata"]
        meta = _json.loads(raw) if isinstance(raw, str) else dict(raw)
        clf = meta.get("triage_classification") or {}
        print("  session   : " + str(m["id"])[:8] + "...")
        print("  classified: " + str(clf.get("classified")))
        print("  symptoms  : " + str(clf.get("symptoms_summary")))
        print("  red_flags : " + str(clf.get("red_flags")))
        print("  level     : " + str(clf.get("level")))

    await conn.close()


asyncio.run(main())
