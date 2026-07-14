"""Table-driven red-flag tests pinned to the seeded MFU criteria."""

import pytest

from app.services.screening.rules.red_flags import evaluate_red_flags


def hits_for(criteria, findings=None, vitals=None, age=None):
    result = evaluate_red_flags(
        findings=findings or {},
        vitals=vitals or {},
        age_years=age,
        criteria=criteria,
    )
    return {h.rule_id for h in result}, result


CASES = [
    # (name, findings, vitals, age, expected rule id present)
    ("cardiac arrest", {"cardiac_arrest": "present"}, {}, 40, "l1_cardiac_arrest"),
    ("unresponsive", {"unresponsive": "present"}, {}, None, "l1_unresponsive"),
    ("adult tachycardia >150", {}, {"hr": 160}, 40, "l1_adult_hr_high"),
    ("age unknown assumes adult", {}, {"hr": 160}, None, "l1_adult_hr_high"),
    ("adult bradycardia + chest pain", {"chest_pain": "present"}, {"hr": 45}, 50, "l1_adult_hr_low_symptomatic"),
    ("adult shock BP", {}, {"sbp": 85}, 30, "l1_adult_shock_bp"),
    ("adult RR > 30", {}, {"rr": 34}, 30, "l1_adult_rr_extreme"),
    ("adult SpO2 < 90 with dyspnea", {"dyspnea": "present"}, {"spo2": 88}, 30, "l1_adult_spo2_low"),
    ("infant HR > 220", {}, {"hr": 230}, 0.5, "l1_child_hr_infant"),
    ("child HR > 180", {}, {"hr": 190}, 6, "l1_child_hr_over1y"),
    ("child HR < 60", {}, {"hr": 55}, 4, "l1_child_hr_low"),
    ("child cyanosis", {"blue_lips": "present"}, {}, 2, "l1_child_cyanosis"),
    ("child SpO2 < 90", {}, {"spo2": 88}, 7, "l1_child_spo2"),
    ("active labor", {"uterine_contractions_frequent": "present"}, {"pain_score": 8}, 28, "l1_ob_active_labor"),
    ("crowning", {"crowning": "present"}, {}, 30, "l1_ob_active_labor"),
    ("pregnant seizure", {"pregnancy": "present", "seizure_now": "present"}, {}, 30, "l1_pregnancy_seizure"),
    ("hypertensive crisis", {}, {"sbp": 185}, 55, "dv_adult_bp_crisis"),
    ("hypertensive crisis dbp", {}, {"dbp": 115}, 55, "dv_adult_bp_crisis"),
    ("adult resting HR > 120", {}, {"hr": 125}, 40, "dv_adult_hr_120_rest"),
    ("adult RR 21-30 + retraction", {"retraction": "present"}, {"rr": 24}, 40, "dv_adult_rr_retraction"),
    ("child 1-3y RR > 40", {}, {"rr": 45}, 2, "dv_child_1_3y"),
    ("child 3-5y HR > 120", {}, {"hr": 130}, 4, "dv_child_3_5y"),
    ("child 5-10y SBP low", {}, {"sbp": 85}, 8, "dv_child_5_10y"),
    ("child 10-15y RR > 20", {}, {"rr": 24}, 12, "dv_child_10_15y"),
    ("child work of breathing", {"retraction": "present", "nasal_flaring": "present"}, {}, 3, "dv_child_work_of_breathing"),
    ("child SpO2 < 94", {}, {"spo2": 93}, 5, "dv_child_spo2_94"),
    ("child severe pain", {}, {"pain_score": 8}, 9, "dv_child_severe_pain"),
    ("stroke BEFAST facial droop", {"facial_droop": "present"}, {}, 60, "ft_stroke_befast"),
    ("stroke BEFAST weakness", {"limb_weakness": "present"}, {}, 45, "ft_stroke_befast"),
    ("MI radiating chest pain", {"chest_pain_radiating": "present"}, {}, 50, "ft_mi_chest_pain"),
    ("GI bleed hematemesis", {"hematemesis": "present"}, {}, 40, "surg_gi_bleed"),
    ("melena", {"melena": "present"}, {}, 40, "surg_gi_bleed"),
    ("severe pain critical site", {"abdominal_pain": "present"}, {"pain_score": 8}, 30, "surg_severe_pain_critical_site"),
    ("major trauma", {"major_trauma_mechanism": "present"}, {}, 25, "surg_major_trauma"),
    ("penetrating injury", {"penetrating_injury_torso": "present"}, {}, 25, "surg_penetrating"),
    ("fracture within 24h", {"fracture_suspected": "present", "injury_within_24h": "present"}, {}, 30, "ortho_fracture_24h"),
    ("suspected ectopic", {"missed_period": "present", "abdominal_pain": "present", "vaginal_bleeding": "present"}, {"pain_score": 8}, 28, "obgyn_ectopic_suspect"),
    ("heavy vaginal bleeding", {"heavy_vaginal_bleeding": "present"}, {}, 35, "obgyn_heavy_bleeding"),
    ("GA>=24w with fluid leak", {"ga_24w_or_more": "present", "amniotic_fluid_leak": "present"}, {}, 30, "ob_ga24_warning"),
    ("eye chemical", {"eye_chemical_exposure": "present"}, {}, 30, "eye_chemical"),
    ("uncontrolled epistaxis", {"epistaxis_uncontrolled": "present"}, {}, 40, "ent_epistaxis_uncontrolled"),
    ("ENT foreign body 24h", {"foreign_body_ent_24h": "present"}, {}, 20, "ent_foreign_body_24h"),
    ("suicidal ideation", {"suicidal_ideation": "present"}, {}, 30, "psych_code_purple"),
    ("overdose", {"overdose_or_poison": "present"}, {}, 30, "med_overdose_poison"),
    ("syncope 24h", {"syncope_24h": "present"}, {}, 60, "med_syncope_24h"),
    ("adult confusion 72h", {"confusion": "present"}, {}, 70, "med_confusion_72h"),
    ("assault 24h", {"assault_24h": "present"}, {}, 30, "forensic_assault"),
    ("child scald 24h", {"burn_scald_24h": "present"}, {}, 4, "peds_accident_24h"),
    ("child palm/sole rash isolation", {"palm_sole_rash": "present"}, {}, 3, "peds_palm_sole_rash_isolation"),
    ("thunderclap headache", {"headache_sudden_severe": "present"}, {}, 40, "headache_thunderclap"),
    ("fever + stiff neck", {"fever": "present", "stiff_neck": "present"}, {}, 30, "meningitis_suspect"),
    ("chest pain + sweating tuple", {"chest_pain": "present", "diaphoresis": "present"}, {}, 50, "tt_chest_pain_diaphoresis"),
    ("chest pain + dyspnea tuple", {"chest_pain": "present", "dyspnea": "present"}, {}, 50, "tt_chest_pain_dyspnea"),
    ("anaphylaxis with systemic sign", {"rash_itching": "present", "lip_swelling": "present", "vomiting": "present"}, {}, 30, "tt_anaphylaxis"),
    ("fever during chemo", {"fever": "present", "recent_chemotherapy": "present"}, {}, 55, "tt_fever_chemo"),
    ("pregnancy + hypertension", {"pregnancy": "present", "hypertension_history": "present"}, {}, 30, "tt_pregnancy_hypertension"),
    ("TB suspect isolation", {"chronic_cough_2w": "present", "hemoptysis": "present"}, {}, 40, "tt_tb_suspect"),
]


@pytest.mark.parametrize("name,findings,vitals,age,expected", CASES, ids=[c[0] for c in CASES])
def test_rule_fires(criteria, name, findings, vitals, age, expected):
    ids, _ = hits_for(criteria, findings, vitals, age)
    assert expected in ids


NEGATIVE_CASES = [
    ("adult vitals do not fire child bands", {}, {"hr": 130}, 40, "dv_child_1_3y"),
    ("child does not fire adult L1 HR rule", {}, {"hr": 160}, 5, "l1_adult_hr_high"),
    ("unknown age never fires child bands", {}, {"hr": 230}, None, "l1_child_hr_infant"),
    ("fracture without 24h window", {"fracture_suspected": "present"}, {}, 30, "ortho_fracture_24h"),
    ("anaphylaxis needs a systemic sign", {"rash_itching": "present", "lip_swelling": "present"}, {}, 30, "tt_anaphylaxis"),
    ("absent finding does not fire tuple", {"chest_pain": "absent", "diaphoresis": "present"}, {}, 50, "tt_chest_pain_diaphoresis"),
    ("moderate pain alone no critical-site rule", {"abdominal_pain": "present"}, {"pain_score": 5}, 30, "surg_severe_pain_critical_site"),
    ("normal adult vitals fire nothing", {}, {"hr": 80, "rr": 16, "sbp": 120, "spo2": 98}, 30, "*any*"),
]


@pytest.mark.parametrize("name,findings,vitals,age,not_expected", NEGATIVE_CASES, ids=[c[0] for c in NEGATIVE_CASES])
def test_rule_does_not_fire(criteria, name, findings, vitals, age, not_expected):
    ids, _ = hits_for(criteria, findings, vitals, age)
    if not_expected == "*any*":
        assert ids == set()
    else:
        assert not_expected not in ids


def test_hits_sorted_most_severe_first(criteria):
    _, result = hits_for(
        criteria,
        {"cardiac_arrest": "present", "chest_pain": "present", "diaphoresis": "present"},
        {},
        50,
    )
    assert result[0].level == 1
    assert [h.level for h in result] == sorted(h.level for h in result)


def test_determinism(criteria):
    args = dict(
        findings={"chest_pain": "present", "diaphoresis": "present"},
        vitals={"hr": 125.0},
        age_years=50.0,
    )
    first, _ = hits_for(criteria, args["findings"], args["vitals"], args["age_years"])
    for _ in range(3):
        again, _ = hits_for(criteria, args["findings"], args["vitals"], args["age_years"])
        assert again == first
