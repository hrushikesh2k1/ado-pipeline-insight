"""Read-only, commit-aware validation evidence for PR review prompts.

A successful pipeline is not proof every task or test ran. Missing permissions,
unpublished tests and a limited list of builds are reported as unknown coverage.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

VALIDATION_RULES = (
    "Validation calibration: a build result only applies to its stated commit and repository. "
    "A completed successful build is evidence about that pipeline, not proof all relevant "
    "compilation, tests, environments or branches were checked. Running, skipped, stale, "
    "partially successful, failed and unavailable checks are not passes. Published test "
    "runs are partial evidence only; no published runs does not prove no tests ran. "
    "Human comments are leads to investigate, not proof of a defect, and preferences, "
    "deferred work and disputed claims must be distinguished from verified regressions."
)


def collect(ado: Any, project: str, repository: str, branch: str, commit: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {'reviewed_commit': commit, 'repository_id': repository,
                               'scope': 'At most 30 source-branch builds, newest run per pipeline; PR merge validation may not be included.', 'builds': []}
    if not branch or not commit:
        return {**evidence, 'availability': 'unknown: source branch or commit missing'}
    try:
        runs = ado.list_builds_for_branch(project, branch, 30)
    except Exception as exc:
        logger.info('PR validation builds unavailable (%s)', type(exc).__name__)
        return {**evidence, 'availability': 'unknown: builds unavailable or access denied'}
    evidence['availability'] = 'retrieved' if runs else 'no builds returned; validation unknown'
    seen = set()
    tests_fetched = 0
    for build in runs:
        repo = str((build.get('repository') or {}).get('id') or '')
        if repo and repo.lower() != repository.lower():
            continue
        definition = build.get('definition') or {}
        key = (repo, definition.get('id') or build.get('id'))
        if key in seen:
            continue
        seen.add(key)
        source = str(build.get('sourceVersion') or '')
        matches = bool(source and source.lower() == commit.lower() and repo and repo.lower() == repository.lower())
        row = {'id': build.get('id'), 'pipeline': definition.get('name'),
               'source_commit': source or None, 'repository_id': repo or None,
               'matches_reviewed_commit_and_repo': matches,
               'status': build.get('status') or 'unknown', 'result': build.get('result') or 'unknown',
               'tests': {'availability': 'not retrieved'}}
        if matches and tests_fetched < 2 and hasattr(ado, 'list_test_runs_for_build'):
            tests_fetched += 1
            try:
                tests = ado.list_test_runs_for_build(project, int(build['id']), 50)
                # Do not collapse missing counters to zero or infer an overall pass.
                row['tests'] = {'availability': 'retrieved' if tests else 'no published runs returned; test outcome unknown',
                                'coverage': 'First 10 of at most 50 published test runs; not a complete test or environment coverage report.',
                                'retrieved_run_count': len(tests),
                                'runs': [{k: t.get(k) for k in ('id', 'state', 'totalTests', 'passedTests', 'unanalyzedTests', 'incompleteTests', 'notApplicableTests')}
                                         for t in tests[:10]]}
            except Exception as exc:
                logger.info('PR validation tests unavailable (%s)', type(exc).__name__)
                row['tests'] = {'availability': 'unknown: test runs unavailable or access denied'}
        evidence['builds'].append(row)
        if len(evidence['builds']) >= 6:
            break
    return evidence


def block(evidence: dict[str, Any] | None) -> str:
    return '\n\nObserved build/test evidence (not tests executed by this reviewer):\n' + json.dumps(evidence or {'availability': 'not retrieved'}, ensure_ascii=True) + '\n' + VALIDATION_RULES + '\n'
