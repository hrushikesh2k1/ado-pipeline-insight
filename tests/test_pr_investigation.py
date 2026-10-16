"""Behavioral regression cases for repository-aware review, using a controlled model.

These validate the review pipeline, not the quality of a live model's reasoning.
"""
import time


from app.services import pr_investigation, pr_review
from app.services.pr_diff import build_view
from app.services.pr_lookup import RepoReader
from pr_support import FakeAdo, FakePrModel, change, finding

SOURCE = 'def get_total():\n    return {"total": 3}\n'
CALLER = 'from api import get_total\nvalue = get_total()["count"]\n'


def setup(model=None):
    ado = FakeAdo(changes=[change('/api.py'), change('/client.py', 'add')],
                  blobs={'old-/api.py': 'def get_total():\n    return {"count": 3}\n',
                         'new-/api.py': SOURCE, 'new-/client.py': CALLER}, description='Rename total in the API')
    return ado, model or FakePrModel()


def defect():
    return finding(2, 'Caller still reads the removed key', evidence='return {"total": 3}',
                   comment='client.py reads count, but this return now exposes total. Update the caller or preserve the contract.',
                   failing_case='Running client.py raises KeyError for count instead of returning 3.',
                   trace='api.py:2 returns {"total": 3}; client.py:2 indexes count, which is absent, so KeyError is raised.',
                   file_path='api.py')


def intercept(monkeypatch, answer):
    original = pr_review.chat_json_with_tools
    calls = []
    def call(model, system, user, tools, run_tool, **kwargs):
        if system == pr_investigation.INTEGRATION_SYSTEM:
            calls.append(user)
            # A real discovery call can read the full source of the related caller.
            assert 'get_total()["count"]' in run_tool('read_file', {'path': 'client.py'})
            if isinstance(answer, Exception):
                raise answer
            return answer
        return original(model, system, user, tools, run_tool, **kwargs)
    monkeypatch.setattr(pr_review, 'chat_json_with_tools', call)
    monkeypatch.setattr('app.services.llm_util.time.sleep', lambda _: None)
    return calls


def test_cross_file_bug_discovered_when_isolated_reviews_find_nothing(monkeypatch):
    calls = intercept(monkeypatch, {'findings': [defect()]})
    ado, model = setup()
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert len(calls) == 1 and 'edit: api.py' in calls[0] and 'add: client.py' in calls[0]
    assert len(result['comments']) == 1
    comment = result['comments'][0]
    assert comment['verified'] is True and comment['file_path'] == 'api.py'
    assert 'client.py:2' in comment['trace'] and 'read client.py' in comment['checked_with']
    assert 'Interaction evidence' in model.calls_of('verify')[0]
    assert any('Cross-file investigation completed 1 of 1' in n for n in result['notes'])


def test_disproved_cross_file_candidate_is_removed(monkeypatch):
    intercept(monkeypatch, {'findings': [defect()]})
    ado, model = setup(FakePrModel(holds=lambda path, numbers: {n: False for n in numbers}))
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert result['comments'] == []
    assert any('removed' in n.lower() for n in result['notes'])


def test_unverified_integration_candidate_never_becomes_a_finding(monkeypatch):
    intercept(monkeypatch, {'findings': [defect()]})
    ado, model = setup(FakePrModel(holds=lambda *args: RuntimeError('model unavailable')))
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert result['comments'] == []


def test_integration_cannot_comment_on_unchanged_or_unknown_files(monkeypatch):
    bad_anchor = {**defect(), 'line': 1, 'evidence': 'def get_total():'}
    unknown = {**defect(), 'file_path': 'outside.py'}
    intercept(monkeypatch, {'findings': [bad_anchor, unknown]})
    ado, model = setup()
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert result['comments'] == []


def test_integration_failure_keeps_file_reviews_and_reports_partial_coverage(monkeypatch):
    intercept(monkeypatch, RuntimeError('integration unavailable'))
    ado, model = setup()
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert all(f['status'] == 'reviewed' for f in result['files'])
    assert any('Cross-file investigation is partial' in n for n in result['notes'])


def test_discovery_can_follow_python_callers_before_it_has_any_findings():
    ado, model = setup(FakePrModel(first_lookups={'api.py': [('read_file', {'path': 'client.py'})]}))
    pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert model.first_tools_offered and all(model.first_tools_offered)
    assert any('get_total()["count"]' in r for r in model.first_tool_results)
    assert ado.item_calls == []  # changed source files reused, not fetched again


def test_source_cache_never_contains_base_version():
    ado, _ = setup()
    reader = RepoReader(ado, 'proj', 'repo', 'source', ['api.py'])
    reader.seed('api.py', SOURCE)
    assert reader.read('/api.py') == (SOURCE, None)
    assert '"count"' not in reader.read_lines('api.py')


def test_batch_and_excerpt_limits_are_explicit():
    views = [build_view(f'file{i}.py', 'Python', 'add', '', 'x = 1\n') for i in range(14)]
    batches = pr_investigation.batches(views)
    assert [len(b) for b in batches] == [6, 6, 2]
    assert sum(batches, []) == views
    views[0].shown = 'x' * 8000
    assert 'excerpt clipped' in pr_investigation.excerpt(views[0])
    assert len(pr_investigation.related_context(views[1], views)) < 12300


def test_expired_budget_skips_interactions_with_visible_coverage_note():
    ado, model = setup()
    service = pr_review.PullRequestReviewService(ado, model)
    views = [build_view('api.py', 'Python', 'edit', 'old\n', SOURCE), build_view('client.py', 'Python', 'add', '', CALLER)]
    notes = []
    service._review_interactions(views, {'api.py': {}, 'client.py': {}}, {}, [],
                                 RepoReader(ado, 'p', 'r', 'source'), time.monotonic() - 1,
                                 lambda *args: None, notes)
    assert any('completed 0 of 1' in note for note in notes)
    assert model.calls == []


def test_same_finding_from_file_and_integration_pass_is_shown_once(monkeypatch):
    intercept(monkeypatch, {'findings': [defect()]})
    ado, model = setup(FakePrModel({'api.py': [defect()]}))
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert len(result['comments']) == 1


def test_related_changes_are_in_the_first_and_independent_review_prompts():
    ado, model = setup(FakePrModel({'api.py': [defect()]}))
    pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    for kind in ('file', 'verify', 'refute'):
        prompts = [p for p in model.calls_of(kind) if p.startswith('File: api.py')]
        assert prompts and 'get_total()["count"]' in prompts[0]


def test_refutation_can_remove_a_claim_with_real_supporting_source(monkeypatch):
    model = FakePrModel(refutes={'api.py': {1: ('caller does not read count', 'value = get_total()["total"]')}})
    ado, model = setup(model)
    ado.blobs['new-/client.py'] = 'from api import get_total\nvalue = get_total()["total"]\n'
    # This test uses a different caller, so discovery must read that actual version.
    from app.services.llm_util import chat_json_with_tools
    def discover(model, system, user, tools, run_tool, **kwargs):
        if system == pr_investigation.INTEGRATION_SYSTEM:
            run_tool('read_file', {'path': 'client.py'})
            return {'findings': [defect()]}
        return chat_json_with_tools(model, system, user, tools, run_tool, **kwargs)
    monkeypatch.setattr(pr_review, 'chat_json_with_tools', discover)
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    assert result['comments'] == []
