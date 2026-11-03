"""Audit-only bounded command capture; does not alter application code."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
label, timeout, *command = sys.argv[1:]
env = os.environ.copy()
env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
start = time.monotonic()
stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
try:
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=float(timeout))
    stdout, stderr, code = result.stdout, result.stderr, result.returncode
except subprocess.TimeoutExpired as exc:
    stdout, stderr, code = exc.stdout or b"", exc.stderr or b"", 124
duration = time.monotonic() - start
out = HERE / "evidence"
out.mkdir(exist_ok=True)
for suffix, data in (("stdout", stdout), ("stderr", stderr)):
    (out / f"{label}.{suffix}.txt").write_bytes(data)
metadata = dict(command=command, cwd=str(ROOT), started_utc=stamp, duration_s=duration,
    timeout_s=float(timeout), exit_code=code, python=sys.version, platform=platform.platform(),
    head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    environment_overrides={k: env[k] for k in ["PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"]},
    stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest())
(out / f"{label}.command.json").write_text(json.dumps(metadata, indent=2)+"\n")
print(json.dumps(dict(label=label, exit_code=code, duration_s=duration)))
print(stdout.decode(errors="replace")[-2500:])
print(stderr.decode(errors="replace")[-1000:])
sys.exit(code)
