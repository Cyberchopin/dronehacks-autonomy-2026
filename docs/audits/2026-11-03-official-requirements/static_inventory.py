"""Read-only inventory restricted to this repository; audit outputs go to stdout."""
import ast
import collections
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

root = Path.cwd()
def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()
files = git("ls-files").splitlines()
hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
broken = []
for name in files:
    if not name.endswith(".md"):
        continue
    for target in re.findall(r"\]\(([^)]+)\)", (root/name).read_text()):
        target = target.split("#")[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        if not (root/name).parent.joinpath(target).exists():
            broken.append(dict(file=name, target=target))
rows = list(csv.DictReader((root/'provenance/third_party.csv').open()))
verifier = ast.parse((root/'provenance/verify_consistency.py').read_text())
required = []
for node in verifier.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DELIVERABLES' for t in node.targets):
        required = ast.literal_eval(node.value)
required += ['provenance/audit-evidence.json']
symbols = {}
for name in files:
    if name.startswith('src/') and name.endswith('.py'):
        tree = ast.parse((root/name).read_text())
        symbols[name] = [dict(name=n.name,line=n.lineno) for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef))]
packages = {}
for n in ['numpy','opencv-python','pyulog','pytest','ruff','setuptools']:
    try:
        packages[n] = importlib.metadata.version(n)
    except importlib.metadata.PackageNotFoundError:
        packages[n] = 'NOT_INSTALLED (build isolation may provide it during installation)'
report = dict(root=str(root), branch=git('branch','--show-current'),head=git('rev-parse','HEAD'),
    remote=git('remote','-v'),status=git('status','--short','--branch'),tracked_count=len(files),
    codegraph_present=(root/'.codegraph').exists(), agent_files=[n for n in files if n.endswith('AGENTS.md')],
    python=sys.version,platform=platform.platform(),machine=platform.machine(),packages=packages,
    tracked_sha256=hashes,symbols=symbols,broken_markdown_links=broken,
    provenance=dict(rows=len(rows),categories=dict(collections.Counter(r['artifact_kind'] for r in rows)),
        missing_verifier_inputs=[n for n in required if not (root/n).exists()],
        original_verifier_execution='NOT_RUN: writes canonical provenance report; missing migrated inputs; no external cache accessed'),
    tracked_assets=[n for n in files if Path(n).suffix.lower() in {'.npz','.ulg','.bag','.onnx','.pt','.engine','.so','.obj','.step','.glb','.mtl'}])
print(json.dumps(report,indent=2))
