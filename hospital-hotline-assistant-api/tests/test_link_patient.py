"""POST /sessions/{id}/link-patient — the HN-first identity write.

Drives the handler directly with an in-file fake connection + adapter (no
DB): the exact ``metadata.patient`` shape, the VN passthrough, the prefill
strip on relink, and the not-found path.
"""

from types import SimpleNamespace
from uuid import uuid4

from app.routers.sessions import link_patient
from app.schemas import LinkPatientRequest
from app.services.screening.his import CurrentVisit, PatientHistory, PatientInfo


class _Conn:
    def __init__(self, metadata):
        self.metadata = dict(metadata)
        self.messages: list = []

    async def fetchrow(self, sql, *args):
        return {"metadata": dict(self.metadata), "language": "th"}

    async def fetchval(self, sql, *args):
        return bool(self.messages)  # EXISTS(messages)

    async def execute(self, sql, *args):
        if "UPDATE sessions" in sql:
            self.metadata = dict(args[1])
        elif "INSERT INTO messages" in sql:
            self.messages.append(args[1])


class _Adapter:
    def __init__(self, info):
        self.info = info
        self.asked: list[str] = []

    async def validate_patient(self, hn):
        self.asked.append(hn)
        return self.info


def _request(adapter):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(his_adapter=adapter)))


INFO = PatientInfo(
    hn="09900001",
    patient_name="สมชาย ใจดี",
    birthdate="1985-03-12",
    age_years=41,
    gender="male",
    patient_history=PatientHistory(
        is_first_time=False,
        smoking="5/day",
        alcohol="social",
        chronic_conditions="hypertension",
        recorded_at="2026-07-05",
        last_weight_kg=72.5,
        last_height_cm=172,
        vitals_measured_at="2026-07-05",
    ),
    current_visit=CurrentVisit(visit_id="990000000000000001", appointment=True),
)


async def test_link_writes_patient_block_with_visit_passthrough():
    conn = _Conn({"slip_code": "MCH-1"})
    out = await link_patient(
        uuid4(), LinkPatientRequest(hn="09900001"), _request(_Adapter(INFO)), conn
    )
    assert out.linked is True
    assert out.hn == "09900001"
    assert out.patient_name == "สมชาย ใจดี"
    assert out.appointment is True
    assert out.is_first_time is False

    patient = conn.metadata["patient"]
    assert patient["hn"] == "09900001"
    assert patient["visit_id"] == "990000000000000001"   # data, never identity
    assert patient["age_years"] == 41
    assert patient["gender"] == "male"
    assert patient["name_confirmed"] is False            # not preconfirmed
    assert "visit" not in conn.metadata                  # the old key is gone
    # Split history landed per V1 §1.3.
    history = conn.metadata["patient_history"]
    assert history["smoking"] == "5/day"
    assert history["alcohol"] == "social"
    # Greeting persisted for the transcript.
    assert conn.messages


async def test_link_without_open_visit_leaves_passthrough_null():
    info = PatientInfo(
        hn="09900006",
        patient_name="Anucha Thongdee",
        patient_history=PatientHistory(is_first_time=True),
        current_visit=None,
    )
    conn = _Conn({})
    out = await link_patient(
        uuid4(), LinkPatientRequest(hn="09900006"), _request(_Adapter(info)), conn
    )
    assert out.linked is True
    assert out.appointment is None
    assert out.is_first_time is True
    assert conn.metadata["patient"]["visit_id"] is None
    assert conn.metadata["patient"]["appointment"] is None


async def test_relink_strips_previous_patients_prefill():
    # Wrong person rejected the name; the correct patient links next: the
    # previous HN's history and HIS-sourced vitals must not carry over.
    conn = _Conn({
        "patient_history": {"is_first_time": False, "chronic_conditions": "old-patient"},
        "vitals": {"weight_kg": 90.0, "source": "his_recent"},
    })
    await link_patient(
        uuid4(), LinkPatientRequest(hn="09900001", preconfirmed=True),
        _request(_Adapter(INFO)), conn,
    )
    assert conn.metadata["patient_history"]["chronic_conditions"] == "hypertension"
    # preconfirmed carries the already-spoken confirmation.
    assert conn.metadata["patient"]["name_confirmed"] is True
    # The stripped HIS vitals were replaced by the new patient's recency merge.
    assert conn.metadata["vitals"].get("weight_kg") != 90.0


async def test_unknown_hn_links_false():
    conn = _Conn({})
    out = await link_patient(
        uuid4(), LinkPatientRequest(hn="00000000"), _request(_Adapter(None)), conn
    )
    assert out.linked is False
    assert out.hn == "00000000"
    assert "patient" not in conn.metadata
