"""Finding model and clean-gate policy.

Any P0, P1, or P2 finding fails the clean gate (P2 is hard-fail, not soft).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional


SEVERITIES = ('P0', 'P1', 'P2')


@dataclass
class Finding:
    severity: str  # P0 | P1 | P2
    layer: str
    persona: str
    passage_id: int
    utterance: str
    detail: str
    invariant: str = ''
    intent: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        sev = str(self.severity or '').upper()
        if sev not in SEVERITIES:
            raise ValueError(f'invalid severity {self.severity!r}; expected one of {SEVERITIES}')
        self.severity = sev

    def to_dict(self) -> dict:
        return asdict(self)


def severity_counts(findings: Iterable[Finding]) -> dict[str, int]:
    counts = {'P0': 0, 'P1': 0, 'P2': 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


def clean_gate(findings: Iterable[Finding]) -> tuple[bool, str]:
    """Return (passed, rationale). ANY P0/P1/P2 fails."""
    findings = list(findings)
    counts = severity_counts(findings)
    total = sum(counts.values())
    if total == 0:
        return True, 'Clean gate passed: zero P0/P1/P2 findings.'
    parts = [f'{k}={v}' for k, v in counts.items() if v]
    return False, f'Clean gate FAILED: {", ".join(parts)} (any severity fails).'


def worst_severity(findings: Iterable[Finding]) -> Optional[str]:
    order = {'P0': 0, 'P1': 1, 'P2': 2}
    best: Optional[str] = None
    for f in findings:
        if best is None or order[f.severity] < order[best]:
            best = f.severity
    return best
