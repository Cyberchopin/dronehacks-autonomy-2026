"""Evidence types; execution is deliberately absent from constructor inputs."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Knowledge = Literal["observed", "inferred", "unknown"]
PX4_CLOCK = "px4_boot_us"
JETSON_CLOCK = "jetson_monotonic_ns"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(text: str) -> object:
    def constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def pairs(items: list[tuple]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, parse_constant=constant, object_pairs_hook=pairs)


def finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (isinstance(value, int) or math.isfinite(value))
    )


def integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**63 - 1


@dataclass(frozen=True)
class Sample:
    source: str
    stream: str
    index: int
    timestamp: int | None
    clock: str
    values: dict

    @property
    def executed(self) -> Literal[False]:
        return False


@dataclass(frozen=True)
class Finding:
    category: str
    knowledge: Knowledge
    source: str
    stream: str
    index: int | None
    timestamp: int | None
    clock: str | None
    detail: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {**asdict(self), "executed": False}


@dataclass
class Ingestion:
    source: str
    path: str | None = None
    sha256: str | None = None
    parser: str | None = None
    samples: list[Sample] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    complete: bool = True

    def issue(
        self,
        category: str,
        detail: str,
        *,
        index: int | None = None,
        knowledge: Knowledge = "unknown",
        stream: str = "input",
    ) -> None:
        self.findings.append(
            Finding(category, knowledge, self.source, stream, index, None, None, detail)
        )
        self.complete = False


def read_snapshot(path: Path, result: Ingestion) -> bytes | None:
    result.path = str(path)
    try:
        data = path.read_bytes()
    except OSError as error:
        result.issue("input_error", f"Cannot read input: {error}")
        return None
    result.sha256 = sha256(data)
    result.metadata["bytes"] = len(data)
    if not data:
        result.issue("empty_input", "Input contains no bytes; behavior is unknown.")
        return None
    return data
