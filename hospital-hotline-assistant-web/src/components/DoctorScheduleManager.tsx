import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api';
import type { DepartmentOut, DoctorOut, DoctorScheduleOut, DoctorWithSchedulesOut } from '../api';

// ── helpers ──────────────────────────────────────────────────────────────────

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatDate(iso: string): string {
  return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {
    weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
  });
}

// ── form state types ─────────────────────────────────────────────────────────

interface SlotFormState {
  doctor_id: string;
  schedule_date: string;
  start_time: string;
  end_time: string;
  break_start: string;
  break_end: string;
  room: string;
  slot_label: string;
  is_available: boolean;
  notes: string;
}

const EMPTY_SLOT: SlotFormState = {
  doctor_id: '',
  schedule_date: todayIso(),
  start_time: '08:00',
  end_time: '12:00',
  break_start: '',
  break_end: '',
  room: '',
  slot_label: '',
  is_available: true,
  notes: '',
};

interface DoctorFormState {
  full_name: string;
  title: string;
  specialization: string;
  department_id: string;
  phone_ext: string;
  notes: string;
  is_active: boolean;
}

const EMPTY_DOCTOR: DoctorFormState = {
  full_name: '',
  title: 'Dr.',
  specialization: '',
  department_id: '',
  phone_ext: '',
  notes: '',
  is_active: true,
};

interface Props {
  departments: DepartmentOut[];
}

// ── component ────────────────────────────────────────────────────────────────

export function DoctorScheduleManager({ departments }: Props) {
  const { t } = useTranslation();

  const [doctors, setDoctors] = useState<DoctorOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // schedule list view
  const [selectedDoctor, setSelectedDoctor] = useState<DoctorWithSchedulesOut | null>(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [viewFromDate, setViewFromDate] = useState(todayIso());

  // doctor form
  const [showDoctorForm, setShowDoctorForm] = useState(false);
  const [editingDoctor, setEditingDoctor] = useState<DoctorOut | null>(null);
  const [doctorForm, setDoctorForm] = useState<DoctorFormState>(EMPTY_DOCTOR);
  const [doctorSaving, setDoctorSaving] = useState(false);

  // slot form
  const [showSlotForm, setShowSlotForm] = useState(false);
  const [editingSlot, setEditingSlot] = useState<DoctorScheduleOut | null>(null);
  const [slotForm, setSlotForm] = useState<SlotFormState>(EMPTY_SLOT);
  const [slotSaving, setSlotSaving] = useState(false);

  // ── data loaders ────────────────────────────────────────────────────────

  const loadDoctors = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listDoctors(false);
      setDoctors(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadDoctors(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadDoctorSchedules = async (doctorId: string, fromDate = viewFromDate) => {
    setScheduleLoading(true);
    try {
      const data = await api.getDoctor(doctorId);
      const schedules = await api.listDoctorSchedules(doctorId, fromDate);
      setSelectedDoctor({ ...data, schedules });
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setScheduleLoading(false);
    }
  };

  // ── doctor CRUD ──────────────────────────────────────────────────────────

  const openAddDoctor = () => {
    setEditingDoctor(null);
    setDoctorForm(EMPTY_DOCTOR);
    setShowDoctorForm(true);
  };

  const openEditDoctor = (doctor: DoctorOut) => {
    setEditingDoctor(doctor);
    setDoctorForm({
      full_name: doctor.full_name,
      title: doctor.title,
      specialization: doctor.specialization ?? '',
      department_id: doctor.department_id ?? '',
      phone_ext: doctor.phone_ext ?? '',
      notes: doctor.notes ?? '',
      is_active: doctor.is_active,
    });
    setShowDoctorForm(true);
  };

  const handleSaveDoctor = async () => {
    if (!doctorForm.full_name.trim()) return;
    setDoctorSaving(true);
    setError(null);
    try {
      const payload = {
        ...doctorForm,
        department_id: doctorForm.department_id || null,
        specialization: doctorForm.specialization || null,
        phone_ext: doctorForm.phone_ext || null,
        notes: doctorForm.notes || null,
      };
      if (editingDoctor) {
        await api.updateDoctor(editingDoctor.id, payload);
      } else {
        await api.createDoctor(payload);
      }
      setShowDoctorForm(false);
      await loadDoctors();
      if (selectedDoctor) await loadDoctorSchedules(selectedDoctor.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setDoctorSaving(false);
    }
  };

  const handleToggleActive = async (doctor: DoctorOut) => {
    try {
      await api.updateDoctor(doctor.id, { is_active: !doctor.is_active });
      await loadDoctors();
      if (selectedDoctor?.id === doctor.id) await loadDoctorSchedules(doctor.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    }
  };

  // ── slot CRUD ────────────────────────────────────────────────────────────

  const openAddSlot = (prefilledDoctorId?: string) => {
    setEditingSlot(null);
    setSlotForm({
      ...EMPTY_SLOT,
      doctor_id: prefilledDoctorId ?? selectedDoctor?.id ?? (doctors[0]?.id ?? ''),
    });
    setShowSlotForm(true);
  };

  const openEditSlot = (slot: DoctorScheduleOut) => {
    setEditingSlot(slot);
    setSlotForm({
      doctor_id: slot.doctor_id,
      schedule_date: typeof slot.schedule_date === 'string'
        ? slot.schedule_date.slice(0, 10)
        : String(slot.schedule_date),
      start_time: typeof slot.start_time === 'string' ? slot.start_time.slice(0, 5) : '',
      end_time:   typeof slot.end_time   === 'string' ? slot.end_time.slice(0, 5)   : '',
      break_start: slot.break_start ? String(slot.break_start).slice(0, 5) : '',
      break_end:   slot.break_end   ? String(slot.break_end).slice(0, 5)   : '',
      room:       slot.room ?? '',
      slot_label: slot.slot_label ?? '',
      is_available: slot.is_available,
      notes:      slot.notes ?? '',
    });
    setShowSlotForm(true);
  };

  const handleSaveSlot = async (keepOpen = false) => {
    if (!slotForm.doctor_id) return;
    setSlotSaving(true);
    setError(null);
    try {
      const payload = {
        schedule_date: slotForm.schedule_date,
        start_time:    slotForm.start_time,
        end_time:      slotForm.end_time,
        break_start:   slotForm.break_start || null,
        break_end:     slotForm.break_end   || null,
        room:          slotForm.room        || null,
        slot_label:    slotForm.slot_label  || null,
        is_available:  slotForm.is_available,
        notes:         slotForm.notes       || null,
      };
      if (editingSlot) {
        await api.updateDoctorSchedule(slotForm.doctor_id, editingSlot.id, payload);
      } else {
        await api.addDoctorSchedule(slotForm.doctor_id, payload);
      }
      // reload the panel for whichever doctor was edited
      if (selectedDoctor?.id === slotForm.doctor_id || !selectedDoctor) {
        await loadDoctorSchedules(slotForm.doctor_id);
      }
      if (keepOpen) {
        // reset date to next day for quick entry
        const next = new Date(slotForm.schedule_date);
        next.setDate(next.getDate() + 1);
        setSlotForm((p) => ({ ...p, schedule_date: next.toISOString().slice(0, 10) }));
        setEditingSlot(null);
      } else {
        setShowSlotForm(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    } finally {
      setSlotSaving(false);
    }
  };

  const handleDeleteSlot = async (slot: DoctorScheduleOut) => {
    if (!window.confirm('Remove this schedule entry?')) return;
    try {
      await api.deleteDoctorSchedule(slot.doctor_id, slot.id);
      if (selectedDoctor) await loadDoctorSchedules(selectedDoctor.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error'));
    }
  };

  // ── derived helpers ──────────────────────────────────────────────────────

  const deptName = (id: string | null) => {
    if (!id) return '—';
    const d = departments.find((x) => x.id === id);
    return d ? d.name_en : '—';
  };

  // Group schedules by date for the list view
  const schedulesByDate = (schedules: DoctorScheduleOut[]) => {
    const map = new Map<string, DoctorScheduleOut[]>();
    for (const s of schedules) {
      const d = typeof s.schedule_date === 'string'
        ? s.schedule_date.slice(0, 10)
        : String(s.schedule_date);
      if (!map.has(d)) map.set(d, []);
      map.get(d)!.push(s);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  };

  // ── render ───────────────────────────────────────────────────────────────

  return (
    <div className="schedule-manager">
      {/* Header */}
      <div className="schedule-manager-header">
        <div>
          <h2>{t('schedulesTitle')}</h2>
          <p className="muted">{t('schedulesSubtitle')}</p>
        </div>
        <div style={{ display: 'flex', gap: '0.6rem' }}>
          <button type="button" className="secondary-btn" onClick={openAddDoctor}>
            + {t('scheduleAddDoctor')}
          </button>
          <button type="button" className="primary-btn" onClick={() => openAddSlot()}>
            + {t('scheduleAddSlot')}
          </button>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="schedule-layout">
        {/* ── Doctor list ── */}
        <aside className="schedule-doctor-list">
          {loading ? (
            <p className="muted">{t('loading')}</p>
          ) : doctors.length === 0 ? (
            <p className="muted">{t('scheduleNoDoctors')}</p>
          ) : (
            doctors.map((doctor) => (
              <div
                key={doctor.id}
                className={`schedule-doctor-card ${selectedDoctor?.id === doctor.id ? 'selected' : ''} ${!doctor.is_active ? 'inactive' : ''}`}
              >
                <button
                  type="button"
                  className="schedule-doctor-card-btn"
                  onClick={() => void loadDoctorSchedules(doctor.id)}
                >
                  <span className="schedule-doctor-name">
                    {doctor.title} {doctor.full_name}
                    {!doctor.is_active && (
                      <span className="schedule-inactive-badge"> (inactive)</span>
                    )}
                  </span>
                  {doctor.specialization && (
                    <span className="schedule-doctor-spec">{doctor.specialization}</span>
                  )}
                  <span className="schedule-doctor-dept">{deptName(doctor.department_id)}</span>
                </button>
                <div className="schedule-doctor-actions">
                  <button type="button" className="icon-text-btn" onClick={() => openEditDoctor(doctor)} title="Edit">✏</button>
                  <button
                    type="button"
                    className="icon-text-btn muted"
                    onClick={() => void handleToggleActive(doctor)}
                    title={doctor.is_active ? t('scheduleDeactivate') : t('scheduleActivate')}
                  >
                    {doctor.is_active ? '⏸' : '▶'}
                  </button>
                </div>
              </div>
            ))
          )}
        </aside>

        {/* ── Schedule panel ── */}
        <section className="schedule-slots-panel">
          {!selectedDoctor ? (
            <div className="schedule-select-hint">
              <p className="muted">← Select a doctor to view their schedule</p>
            </div>
          ) : scheduleLoading ? (
            <p className="muted">{t('loading')}</p>
          ) : (
            <>
              <div className="schedule-slots-header">
                <div>
                  <h3>{selectedDoctor.title} {selectedDoctor.full_name}</h3>
                  {selectedDoctor.specialization && (
                    <span className="muted" style={{ fontSize: '0.8rem' }}>
                      {selectedDoctor.specialization}
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <label className="schedule-field-inline">
                    <span className="muted" style={{ fontSize: '0.78rem' }}>From</span>
                    <input
                      type="date"
                      value={viewFromDate}
                      className="schedule-date-filter"
                      onChange={(e) => {
                        setViewFromDate(e.target.value);
                        void loadDoctorSchedules(selectedDoctor.id, e.target.value);
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => openAddSlot(selectedDoctor.id)}
                  >
                    + {t('scheduleAddSlot')}
                  </button>
                </div>
              </div>

              {selectedDoctor.schedules.length === 0 ? (
                <p className="muted" style={{ marginTop: '1rem' }}>{t('scheduleNoSlots')}</p>
              ) : (
                <div className="schedule-days-grid">
                  {schedulesByDate(selectedDoctor.schedules).map(([dateStr, slots]) => (
                    <div key={dateStr} className="schedule-day-group">
                      <span className="schedule-day-label">{formatDate(dateStr)}</span>
                      {slots.map((slot) => (
                        <div key={slot.id} className={`schedule-slot-row ${!slot.is_available ? 'unavailable' : ''}`}>
                          <span className="schedule-slot-time">
                            {String(slot.start_time).slice(0, 5)}–{String(slot.end_time).slice(0, 5)}
                          </span>
                          {slot.break_start && slot.break_end && (
                            <span className="schedule-slot-break">
                              break {String(slot.break_start).slice(0, 5)}–{String(slot.break_end).slice(0, 5)}
                            </span>
                          )}
                          {slot.room && <span className="schedule-slot-room">Rm {slot.room}</span>}
                          {slot.slot_label && <span className="schedule-slot-tag">{slot.slot_label}</span>}
                          {!slot.is_available && <span className="schedule-slot-unavail-tag">off</span>}
                          <button type="button" className="icon-text-btn" onClick={() => openEditSlot(slot)}>✏</button>
                          <button type="button" className="icon-text-btn danger" onClick={() => void handleDeleteSlot(slot)}>✕</button>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {/* ── Doctor form modal ── */}
      {showDoctorForm && (
        <div className="nurse-review-modal" role="dialog" aria-modal="true">
          <button type="button" className="nurse-review-modal-backdrop" onClick={() => setShowDoctorForm(false)} />
          <div className="nurse-review-modal-card schedule-form-modal">
            <div className="nurse-review-modal-header">
              <h2>{editingDoctor ? t('scheduleEditDoctor') : t('scheduleAddDoctor')}</h2>
              <button type="button" className="icon-btn nurse-review-modal-close" onClick={() => setShowDoctorForm(false)}>×</button>
            </div>
            <div className="schedule-form-body">
              <div className="schedule-form-row">
                <label className="schedule-field" style={{ flex: '0 0 80px' }}>
                  <span>{t('scheduleDoctorTitle')}</span>
                  <input type="text" value={doctorForm.title}
                    onChange={(e) => setDoctorForm((p) => ({ ...p, title: e.target.value }))}
                    placeholder="Dr." />
                </label>
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleDoctorName')} *</span>
                  <input type="text" value={doctorForm.full_name}
                    onChange={(e) => setDoctorForm((p) => ({ ...p, full_name: e.target.value }))}
                    placeholder="Firstname Lastname" />
                </label>
              </div>
              <label className="schedule-field">
                <span>{t('scheduleDoctorSpecialization')}</span>
                <input type="text" value={doctorForm.specialization}
                  onChange={(e) => setDoctorForm((p) => ({ ...p, specialization: e.target.value }))}
                  placeholder="e.g. Internal Medicine" />
              </label>
              <label className="schedule-field">
                <span>{t('scheduleDoctorDept')}</span>
                <select value={doctorForm.department_id}
                  onChange={(e) => setDoctorForm((p) => ({ ...p, department_id: e.target.value }))}>
                  <option value="">— None —</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name_en}</option>
                  ))}
                </select>
              </label>
              <label className="schedule-field">
                <span>{t('scheduleDoctorPhone')}</span>
                <input type="text" value={doctorForm.phone_ext}
                  onChange={(e) => setDoctorForm((p) => ({ ...p, phone_ext: e.target.value }))}
                  placeholder="e.g. 1234" />
              </label>
              <label className="schedule-field schedule-field-checkbox">
                <input type="checkbox" checked={doctorForm.is_active}
                  onChange={(e) => setDoctorForm((p) => ({ ...p, is_active: e.target.checked }))} />
                <span>{t('scheduleDoctorActive')}</span>
              </label>
            </div>
            <div className="nurse-review-modal-actions" style={{ padding: '0 1.5rem 1.5rem' }}>
              <button type="button" className="nurse-approve-btn"
                disabled={doctorSaving || !doctorForm.full_name.trim()}
                onClick={() => void handleSaveDoctor()}>
                {t('scheduleSave')}
              </button>
              <button type="button" className="secondary-btn" onClick={() => setShowDoctorForm(false)}>
                {t('scheduleCancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add / edit schedule slot modal ── */}
      {showSlotForm && (
        <div className="nurse-review-modal" role="dialog" aria-modal="true">
          <button type="button" className="nurse-review-modal-backdrop" onClick={() => setShowSlotForm(false)} />
          <div className="nurse-review-modal-card schedule-form-modal">
            <div className="nurse-review-modal-header">
              <h2>{editingSlot ? t('scheduleEditSlot') : t('scheduleAddSlot')}</h2>
              <button type="button" className="icon-btn nurse-review-modal-close" onClick={() => setShowSlotForm(false)}>×</button>
            </div>

            <div className="schedule-form-body">
              {/* Doctor dropdown */}
              <label className="schedule-field">
                <span>{t('scheduleDoctorName')} *</span>
                <select value={slotForm.doctor_id}
                  onChange={(e) => {
                    const doc = doctors.find((d) => d.id === e.target.value);
                    setSlotForm((p) => ({
                      ...p,
                      doctor_id: e.target.value,
                    }));
                    // auto-fill department display (read-only info)
                    void doc;
                  }}
                  disabled={!!editingSlot}
                >
                  <option value="">— Select doctor —</option>
                  {doctors.filter((d) => d.is_active).map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.title} {d.full_name}{d.specialization ? ` (${d.specialization})` : ''}
                    </option>
                  ))}
                </select>
              </label>

              {/* Department (auto-filled, read only) */}
              {slotForm.doctor_id && (() => {
                const doc = doctors.find((d) => d.id === slotForm.doctor_id);
                return doc?.department_id ? (
                  <div className="schedule-field">
                    <span className="muted" style={{ fontSize: '0.78rem' }}>{t('scheduleDoctorDept')}</span>
                    <div className="schedule-autofill">{deptName(doc.department_id)}</div>
                  </div>
                ) : null;
              })()}

              {/* Date */}
              <label className="schedule-field">
                <span>{t('scheduleSlotDate')} *</span>
                <input type="date" value={slotForm.schedule_date}
                  onChange={(e) => setSlotForm((p) => ({ ...p, schedule_date: e.target.value }))} />
              </label>

              {/* Start / End time */}
              <div className="schedule-form-row">
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleSlotStart')}</span>
                  <input type="time" value={slotForm.start_time}
                    onChange={(e) => setSlotForm((p) => ({ ...p, start_time: e.target.value }))} />
                </label>
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleSlotEnd')}</span>
                  <input type="time" value={slotForm.end_time}
                    onChange={(e) => setSlotForm((p) => ({ ...p, end_time: e.target.value }))} />
                </label>
              </div>

              {/* Break */}
              <div className="schedule-form-row">
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleBreakStart')}</span>
                  <input type="time" value={slotForm.break_start}
                    onChange={(e) => setSlotForm((p) => ({ ...p, break_start: e.target.value }))} />
                </label>
                <span className="schedule-form-to">to</span>
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleBreakEnd')}</span>
                  <input type="time" value={slotForm.break_end}
                    onChange={(e) => setSlotForm((p) => ({ ...p, break_end: e.target.value }))} />
                </label>
              </div>

              {/* Room & label */}
              <div className="schedule-form-row">
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleRoom')}</span>
                  <input type="text" value={slotForm.room}
                    onChange={(e) => setSlotForm((p) => ({ ...p, room: e.target.value }))}
                    placeholder="e.g. 201A" />
                </label>
                <label className="schedule-field" style={{ flex: 1 }}>
                  <span>{t('scheduleSlotLabel')}</span>
                  <input type="text" value={slotForm.slot_label}
                    onChange={(e) => setSlotForm((p) => ({ ...p, slot_label: e.target.value }))}
                    placeholder="Morning / Afternoon…" />
                </label>
              </div>

              {/* Status */}
              <label className="schedule-field schedule-field-checkbox">
                <input type="checkbox" checked={slotForm.is_available}
                  onChange={(e) => setSlotForm((p) => ({ ...p, is_available: e.target.checked }))} />
                <span>{t('scheduleSlotAvailable')}</span>
              </label>

              {/* Notes */}
              <label className="schedule-field">
                <span>{t('scheduleNotes')}</span>
                <input type="text" value={slotForm.notes}
                  onChange={(e) => setSlotForm((p) => ({ ...p, notes: e.target.value }))}
                  placeholder="Optional notes…" />
              </label>
            </div>

            <div className="nurse-review-modal-actions" style={{ padding: '0 1.5rem 1.5rem' }}>
              <button type="button" className="nurse-approve-btn"
                disabled={slotSaving || !slotForm.doctor_id || !slotForm.schedule_date}
                onClick={() => void handleSaveSlot(false)}>
                {t('scheduleSave')}
              </button>
              {!editingSlot && (
                <button type="button" className="secondary-btn"
                  disabled={slotSaving || !slotForm.doctor_id || !slotForm.schedule_date}
                  onClick={() => void handleSaveSlot(true)}>
                  {t('scheduleSaveAndAdd')}
                </button>
              )}
              <button type="button" className="secondary-btn" onClick={() => setShowSlotForm(false)}>
                {t('scheduleCancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
