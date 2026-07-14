"""Deterministic rules: criteria schema, evaluation, disposition, routing."""

from .criteria_models import ScreeningCriteria, parse_criteria
from .department_map import DepartmentDecision, resolve_department
from .disposition import DispositionReason, DispositionResult, decide
from .question_policy import InterviewInputs, is_interview_complete, next_question
from .red_flags import RuleHit, evaluate_red_flags

__all__ = [
    "ScreeningCriteria",
    "parse_criteria",
    "DepartmentDecision",
    "resolve_department",
    "DispositionReason",
    "DispositionResult",
    "decide",
    "InterviewInputs",
    "is_interview_complete",
    "next_question",
    "RuleHit",
    "evaluate_red_flags",
]
