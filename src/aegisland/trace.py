from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .domain import TraceEvent, jsonable


class JsonlTraceStore:
    def __init__(self, path: str | Path, *, truncate: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if truncate:
            self.path.write_text("", encoding="utf-8")

    def write(self, event: TraceEvent | Mapping[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(jsonable(event), sort_keys=True) + "\n")


class CloudTraceStore:
    """Writes locally first, then mirrors traces to the IAM-protected AWS endpoint."""

    def __init__(self, local: JsonlTraceStore, endpoint: str | None = None) -> None:
        self.local = local
        self.endpoint = endpoint or os.getenv("AEGISLAND_TRACE_ENDPOINT")

    def write(self, event: TraceEvent) -> None:
        self.local.write(event)
        if not self.endpoint:
            return
        try:
            import boto3
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
            from botocore.httpsession import URLLib3Session

            body = json.dumps(jsonable(event)).encode()
            region = os.getenv("AWS_REGION", "us-east-1")
            credentials = boto3.Session().get_credentials().get_frozen_credentials()
            request = AWSRequest(
                method="POST",
                url=f"{self.endpoint.rstrip('/')}/traces",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            SigV4Auth(credentials, "execute-api", region).add_auth(request)
            URLLib3Session().send(request.prepare())
        except Exception as exc:  # noqa: BLE001 - cloud loss must never break the safety loop.
            error_path = self.local.path.with_suffix(".cloud-errors.log")
            with error_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{type(exc).__name__}: {exc}\n")


class MemoryTraceStore:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def write(self, event: TraceEvent) -> None:
        self.events.append(event)
