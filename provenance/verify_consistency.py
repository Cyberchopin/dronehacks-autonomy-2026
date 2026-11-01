#!/usr/bin/env python3
"""Verify the bounded audit from local evidence. No network or upstream execution."""

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
DELIVERABLES = [
    'provenance/third_party.csv',
    'docs/upstream-method-matrix.md',
    'docs/license-and-redistribution-review.md',
    'docs/integration-decision.md',
    'docs/handoffs/provenance-HANDOFF.md',
]
AUDIT_FILES = sorted(DELIVERABLES + [
    'provenance/audit-evidence.json',
    'provenance/verification-report.json',
    'provenance/verify_consistency.py',
])
EXPECTED_DECISIONS = {
    'cuvslam': 'CONDITIONAL', 'ros': 'CONDITIONAL',
    'ros_dependency': 'CONDITIONAL', 'euroc': 'CONDITIONAL',
    'depthai': 'CONDITIONAL', 'ffs': 'NO-GO', 'kimera': 'CONDITIONAL',
}
EXPECTED_PROJECT_COUNTS = {
    'cuvslam': 22, 'depthai': 11, 'euroc': 2,
    'ffs': 6, 'kimera': 11, 'ros': 7, 'ros_dependency': 1,
}
HEX256 = re.compile(r'[0-9a-f]{64}')
HEX160 = re.compile(r'[0-9a-f]{40}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def counter(values):
    return dict(sorted(collections.Counter(values).items()))


def relative_path(value):
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and '\\' not in value,
            f'Unsafe or non-relative path: {value!r}')
    require(str(path) == value, f'Noncanonical relative path: {value!r}')
    return path


def git(*args):
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    require(result.returncode == 0,
            f'git {args!r} exited {result.returncode}: {result.stderr}')
    return result.stdout


def candidate_from_label(label):
    if 'Fast-FoundationStereo' in label:
        return 'ffs'
    if 'Kimera-VIO' in label:
        return 'kimera'
    if 'EuRoC' in label:
        return 'euroc'
    if 'DepthAI' in label or 'depthai-core' in label:
        return 'depthai'
    if 'ROS' in label or 'isaac_ros_visual_slam' in label:
        return 'ros'
    if 'cuVSLAM' in label:
        return 'cuvslam'
    return None


def document_decisions(path, text):
    result = {}
    if path.name == 'license-and-redistribution-review.md':
        for line in text.splitlines():
            match = re.match(r'^## (.+?)：(CONDITIONAL|NO-GO|GO)', line)
            if match:
                key = candidate_from_label(match[1])
                require(key and key not in result, f'{path}: ambiguous decision heading {line}')
                result[key] = match[2]
    else:
        title = '## 固定版本与结论' if path.name == 'upstream-method-matrix.md' else (
            '## 使用决定' if path.name == 'integration-decision.md' else '当前结论：')
        require(title in text, f'{path}: missing decision section')
        section = text.split(title, 1)[1]
        lines = section.splitlines()
        started = False
        for line in lines:
            if line.startswith('|'):
                started = True
                cells = [v.strip() for v in line.strip('|').split('|')]
                key = candidate_from_label(cells[0])
                if key:
                    statuses = re.findall(r'\*\*(CONDITIONAL|NO-GO|GO)\*\*', line)
                    require(statuses and key not in result,
                            f'{path}: missing/duplicate candidate status {line}')
                    result[key] = statuses[0]
            elif started:
                break
    dep_lines = [line for line in text.splitlines() if line.startswith('ROS cuVSLAM gitlink `')]
    require(len(dep_lines) == 1, f'{path}: missing/ambiguous ROS dependency decision')
    dep = dep_lines[0]
    require('33da60662b27c0c5b63e0597bd778066af2731ed' in dep and
            '/33da60662b27c0c5b63e0597bd778066af2731ed/LICENSE' in dep,
            f'{path}: incorrect dependency pin/source link')
    statuses = re.findall(r'\*\*(CONDITIONAL|NO-GO|GO)\*\*', dep)
    require(len(statuses) == 1, f'{path}: ambiguous dependency status')
    result['ros_dependency'] = statuses[0]
    require(result == EXPECTED_DECISIONS, f'{path}: decision mismatch {result}')
    require('research/evaluation-only' in text, f'{path}: missing FFS research-only scope')
    require('Triangle' in text, f'{path}: missing fallback distribution gate')
    require('未启用' in text or '未启动' in text, f'{path}: fallback status missing')
    require('接口参考' in text or 'API/示例参考' in text or 'API 参考' in text,
            f'{path}: limited reference scope missing')
    return result


def verify(cache, report_path):
    report = {'status': 'BLOCKED', 'checks': {}, 'errors': [], 'downloads_performed': 0}
    checks = report['checks']
    require((ROOT / 'provenance').is_dir() and (ROOT / '.git').exists(),
            f'Unexpected worktree: {ROOT}')
    expected_report = ROOT / 'provenance/verification-report.json'
    require(report_path == expected_report, 'Report must stay in the current worktree')
    # This generated output is linked by the documents. Materialize its path before
    # checking those links on a first run; no prior report content is trusted.
    report_path.touch(exist_ok=True)
    with (ROOT / DELIVERABLES[0]).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    require(len(fields) == len(set(fields)), 'Duplicate CSV columns')
    require(len(rows) == 60, f'CSV data rows {len(rows)} != 60')
    require(all(None not in row and all(row.values()) for row in rows),
            'Malformed CSV row or empty required field')
    categories = counter(row['artifact_kind'] for row in rows)
    require(categories == {'excluded_large_asset': 2, 'release_asset_metadata_only': 14,
                           'small_source_or_document_evidence': 44}, f'Category mismatch {categories}')
    projects = counter(row['project'] for row in rows)
    require(projects == EXPECTED_PROJECT_COUNTS, f'Project counts mismatch {projects}')
    checks['csv_counts'] = {'data_rows_excluding_header': len(rows), 'categories': categories,
                           'category_sum': sum(categories.values()), 'projects': projects,
                           'project_sum': sum(projects.values())}
    require(len({r['artifact_id'] for r in rows}) == 60, 'Ambiguous artifact IDs')

    evidence = json.loads((ROOT / 'provenance/audit-evidence.json').read_text())
    prior = evidence['prior_final_check_failure']
    require(prior['exit_code'] == 1 and prior['stderr'] == '' and
            prior['failed_assertion'] is None and
            prior['command'] == 'git diff --check --no-index /dev/null docs/integration-decision.md',
            'Missing exact historical failed-command evidence')
    report['prior_failure'] = prior
    report['repair_failures'] = evidence.get('verification_repair_history', [])
    require(len(evidence['files']) == 44, 'Evidence file count mismatch')
    files = {(f['project'], f['path']): f for f in evidence['files']}
    require(len(files) == 44 and all('content' not in f for f in files.values()),
            'Duplicate file identity or vendored source body in evidence')
    assets = {a['name']: a for a in evidence['release_assets_not_downloaded']}
    require(len(assets) == 14, 'Release metadata count mismatch')
    canonical = {}
    source_keys = set()
    bindings = []
    local_count = 0
    upstream_count = 0
    unknown_count = 0
    for row in rows:
        status = row['sha256_verification']
        require(row['decision'] == EXPECTED_DECISIONS[row['project']],
                f'CSV decision mismatch: {row["artifact_id"]}')
        require(row['decision_scope'].startswith('CANDIDATE_COMPETITION_INTEGRATION_AND_REDISTRIBUTION'),
                f'CSV decision scope missing: {row["artifact_id"]}')
        require(row['artifact_id'] == row['project'] + '@' + row['commit'] + ':' + row['artifact'],
                'Incorrect artifact identity')
        if status == 'LOCALLY_COMPUTED_GIT_BLOB_VERIFIED':
            local_count += 1
            key = row['project'], row['artifact']
            require(key in files and key not in source_keys, f'Ambiguous source binding {key}')
            source_keys.add(key)
            f = files[key]
            require(HEX256.fullmatch(row['sha256']) and HEX160.fullmatch(row['commit']),
                    f'Invalid local hash/commit {key}')
            require(row['commit'] in row['url'] and row['url'] == f['raw_url'],
                    f'Unpinned source URL {key}')
            relative_path(row['artifact'])
            rel = str(relative_path(row['local_relative_path']))
            size = int(row['size_bytes'])
            require(rel == 'by-sha256/' + row['sha256'], f'Noncanonical digest path {key}')
            expected = (rel, size)
            require(row['sha256'] not in canonical or canonical[row['sha256']] == expected,
                    f'One digest mapped to conflicting paths/sizes: {key}')
            canonical[row['sha256']] = expected
            require(f['local_relative_path'] == rel and f['size_bytes'] == size and
                    f['sha256'] == row['sha256'] and f['artifact_id'] == row['artifact_id'],
                    f'CSV/JSON hash binding mismatch {key}')
            src_rel = str(relative_path(f['source_cache_relative_path']))
            require(src_rel == row['project'] + '/' + row['artifact'],
                    f'Wrong original cache path {key}')
            for candidate in [cache / rel, cache / src_rel]:
                require(candidate.is_file() and not candidate.is_symlink(), f'Missing/linked local evidence {candidate}')
                require(candidate.resolve().is_relative_to(cache.resolve()), f'Cache escape {candidate}')
                data = candidate.read_bytes()
                require(len(data) == size, f'Byte size mismatch {candidate}')
                require(hashlib.sha256(data).hexdigest() == row['sha256'], f'SHA-256 mismatch {candidate}')
                blob = b'blob ' + str(len(data)).encode() + b'\0' + data
                require(hashlib.sha1(blob).hexdigest() == row['git_blob_sha1'] == f['git_blob_sha1'],
                        f'Git blob mismatch {candidate}')
            require(row['artifact_download_status'] == 'DOWNLOADED_SMALL_TEXT' and
                    row['upstream_sha256_status'] == 'NO_PUBLISHED_SHA256_IN_REVIEWED_EVIDENCE',
                    f'Local publication/download status mismatch {key}')
            bindings.append({'artifact_id': row['artifact_id'], 'source_relative_path': src_rel,
                             'local_relative_path': rel, 'sha256': row['sha256'], 'size_bytes': size})
        elif status == 'UPSTREAM_REPORTED_NOT_LOCALLY_VERIFIED':
            upstream_count += 1
            require(row['artifact'] in assets, f'Unbound upstream digest {row["artifact"]}')
            a = assets[row['artifact']]
            require(HEX256.fullmatch(row['sha256']) and row['sha256'] == a['sha256'] and
                    int(row['size_bytes']) == a['size_bytes'] and row['url'] == a['url'],
                    f'Official metadata binding mismatch {row["artifact"]}')
            require(row['artifact_download_status'] == 'NOT_DOWNLOADED' and
                    row['download_date_utc'] == row['local_relative_path'] == 'NOT_DOWNLOADED' and
                    row['upstream_sha256_status'] == 'OFFICIALLY_PUBLISHED',
                    f'Release download/hash status mismatch {row["artifact"]}')
        else:
            unknown_count += 1
            require(status == 'NOT_VERIFIED' and row['sha256'] == 'UNKNOWN_NOT_ESTABLISHED' and
                    row['size_bytes'] == 'UNKNOWN_NOT_DOWNLOADED' and
                    row['artifact_kind'] == 'excluded_large_asset', 'Invalid unknown-hash record')
            require(row['artifact_download_status'] == 'NOT_DOWNLOADED' and
                    row['download_date_utc'] == row['local_relative_path'] == 'NOT_DOWNLOADED' and
                    row['upstream_sha256_status'] == 'NOT_ESTABLISHED', 'Unknown status conflates absence/download')
    require((local_count, upstream_count, unknown_count) == (44, 14, 2), 'Hash class mismatch')
    require(source_keys == set(files), 'Unbound local evidence record')
    require(len(canonical) == 43 and len({p for p, n in canonical.values()}) == 43,
            'Canonical local paths are ambiguous')
    require(sum(b['size_bytes'] for b in bindings) == 1244609, 'Local byte total mismatch')
    checks['hash_bindings'] = {'local_rows': 44, 'distinct_digests_and_canonical_paths': 43,
                              'source_record_bytes': 1244609, 'bindings': bindings}
    checks['status_axes'] = {
        'hash_verification': counter(r['sha256_verification'] for r in rows),
        'hash_publication': counter(r['upstream_sha256_status'] for r in rows),
        'artifact_download': counter(r['artifact_download_status'] for r in rows),
        'proven_absence_of_any_published_hash': 0,
        'note': 'No published SHA-256 in reviewed metadata is scoped; 2 unselected/undownloaded assets remain unknown, not proven unpublished.',
    }

    decisions = {'provenance/third_party.csv': {
        key: sorted({r['decision'] for r in rows if r['project'] == key})[0]
        for key in EXPECTED_DECISIONS}}
    checked_links = 0
    for name in DELIVERABLES[1:]:
        path = ROOT / name
        data = path.read_bytes()
        text = data.decode('utf-8')
        require(text.endswith('\n') and '\ufffd' not in text and b'\r' not in data,
                f'Encoding/newline issue {name}')
        for number, line in enumerate(text.splitlines(), 1):
            require(line == line.rstrip(' \t'), f'Trailing whitespace {name}:{number}')
        decisions[name] = document_decisions(path, text)
        for target in re.findall(r'\]\(([^)]+)\)', text):
            if target.startswith(('http://', 'https://')):
                require(not re.search(r'github\.com/[^/]+/[^/]+/(blob|tree)/(main|master)/', target),
                        f'Mutable source URL {name}: {target}')
            elif not target.startswith('#'):
                require('\\' not in target and (path.parent / target.split('#')[0]).exists(),
                        f'Broken local Markdown link {name}: {target}')
                checked_links += 1
    require(all(value == EXPECTED_DECISIONS for value in decisions.values()),
            'Dependency decisions disagree across deliverables')
    checks['dependency_decisions_across_five_files'] = decisions
    checks['local_markdown_links_checked'] = checked_links
    checks['markdown_whitespace'] = 'PASS (direct byte/line checks; no diff exit-status normalization)'

    real = ROOT / 'docs/license-and-redistribution-review.md'
    names = [p.name for p in (ROOT / 'docs').iterdir() if 'redistribution' in p.name]
    require(names == ['license-and-redistribution-review.md'] and real.is_file() and not real.is_symlink(),
            f'Wrong license-review filename(s): {names!r}')
    checks['license_review_filename'] = {'relative_path': str(real.relative_to(ROOT)),
                                         'literal_backslash_present': False, 'exists': True}

    require(git('diff', '--name-only') == '' and git('diff', '--cached', '--name-only') == '',
            'Tracked application or index changes outside new audit artifacts')
    status = git('status', '--short', '--untracked-files=all')
    expected_status = ''.join('?? ' + name + '\n' for name in AUDIT_FILES)
    require(status in ('', expected_status), f'Unexpected git status: {status!r}')
    handoff = (ROOT / 'docs/handoffs/provenance-HANDOFF.md').read_text()
    begin = '<!-- verification-git-status:start -->\n```text\n'
    end = '```\n<!-- verification-git-status:end -->'
    require(handoff.count(begin) == 1 and handoff.count(end) == 1,
            'HANDOFF missing exact git-status record')
    recorded_status = handoff.split(begin, 1)[1].split(end, 1)[0]
    require(recorded_status == expected_status,
            'HANDOFF pre-checkpoint git status is stale')
    require('Final verification: **PASS (exit 0)**' in handoff,
            'HANDOFF final verification status missing')
    checks['exact_git_status'] = {'command': 'git status --short --untracked-files=all',
                                  'exit_code': 0, 'stdout': status, 'stderr': ''}
    checks['new_files_only'] = AUDIT_FILES
    checks['tracked_application_and_index_changes'] = 0
    checks['source_bodies_in_persistent_evidence'] = 0
    checks['remaining_unknowns_preserved'] = evidence['limitations']
    report['input_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                              for name in sorted(set(AUDIT_FILES) - {'provenance/verification-report.json'})}
    report['cache_root'] = str(cache)
    report['command'] = 'python3 provenance/verify_consistency.py --cache-root /tmp/gps-denied-provenance-audit --report provenance/verification-report.json'
    report['exit_code'] = 0
    report['status'] = 'PASS'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report_path = (ROOT / args.report).resolve()
    try:
        report = verify(args.cache_root.resolve(), report_path)
    except (ValueError, OSError, KeyError, TypeError, csv.Error, UnicodeError) as error:
        report = {'status': 'BLOCKED', 'exit_code': 1, 'failed_assertion': str(error),
                  'command': shlex.join(['python3', *sys.argv]), 'downloads_performed': 0}
        if report_path == ROOT / 'provenance/verification-report.json':
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 1
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'exit_code': 0, 'data_rows': 60,
                      'categories': report['checks']['csv_counts']['categories'],
                      'local_file_rows': 44, 'canonical_hash_paths': 43,
                      'upstream_unverified_hashes': 14, 'unknown_hash_placeholders': 2,
                      'not_downloaded_artifacts': 16, 'dependency_subjects_crosschecked': 7,
                      'deliverables_crosschecked': 5, 'report': str(report_path.relative_to(ROOT))}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
