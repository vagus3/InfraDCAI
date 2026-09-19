from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionStatus(str, Enum):
    VALID = "VALID"
    VIOLATED = "VIOLATED"
    REVISIT_REQUIRED = "REVISIT_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass
class Evidence:
    source: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Result:
    decision_id: str
    title: str
    status: DecisionStatus
    statement: str
    reason: str
    evidence: list[Evidence] = field(default_factory=list)
