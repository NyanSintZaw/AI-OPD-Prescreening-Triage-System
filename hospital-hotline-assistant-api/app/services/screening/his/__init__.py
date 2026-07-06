"""Hospital Information System integration adapters."""

from .adapter import HisAdapter, VisitInfo
from .mock import MockHisAdapter

__all__ = ["HisAdapter", "VisitInfo", "MockHisAdapter"]
