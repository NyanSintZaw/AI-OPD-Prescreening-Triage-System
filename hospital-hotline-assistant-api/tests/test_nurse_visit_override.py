"""Nurse-entered VN override (_set_visit_passthrough) — no DB."""

from app.routers.admin_reviews import _set_visit_passthrough


class _Conn:
    def __init__(self, metadata):
        self.metadata = metadata
        self.wrote = False

    async def fetchrow(self, sql, *args):
        return None if self.metadata is None else {"metadata": dict(self.metadata)}

    async def execute(self, sql, *args):
        self.metadata = dict(args[1])
        self.wrote = True


async def test_fills_visit_id_on_linked_patient():
    conn = _Conn({"patient": {"hn": "09900001", "visit_id": None}})
    await _set_visit_passthrough(conn, "s1", "  990000000000000009  ")
    assert conn.metadata["patient"]["visit_id"] == "990000000000000009"
    assert conn.metadata["patient"]["hn"] == "09900001"  # identity untouched


async def test_noop_without_patient_link_or_value():
    anon = _Conn({"slip_code": "MCH-1"})
    await _set_visit_passthrough(anon, "s1", "V1")
    assert not anon.wrote  # no HN to hang a VN on

    linked = _Conn({"patient": {"hn": "09900001"}})
    await _set_visit_passthrough(linked, "s1", "   ")
    assert not linked.wrote
