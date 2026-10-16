from app.services import pr_validation, pr_review
from pr_support import FakeAdo, FakePrModel

COMMIT = 'a' * 40


def build(**over):
    return {'id': 7, 'sourceVersion': COMMIT, 'repository': {'id': 'repo'},
            'definition': {'id': 3, 'name': 'CI'}, 'status': 'completed', 'result': 'succeeded', **over}


class Ado(FakeAdo):
    def __init__(self, builds=None, tests=None, denied=False):
        super().__init__(builds=builds if builds is not None else [build()], description='')
        self.tests, self.denied, self.test_calls = tests or [], denied, []

    def list_test_runs_for_build(self, project, build_id, top):
        self.test_calls.append(build_id)
        if self.denied:
            raise PermissionError('denied')
        return self.tests


def collect(ado):
    return pr_validation.collect(ado, 'proj', 'repo', 'refs/heads/feature', COMMIT)


def test_build_and_tests_are_tied_to_the_reviewed_commit():
    ado = Ado(tests=[{'id': 8, 'state': 'Completed', 'totalTests': 10, 'passedTests': 9}])
    result = collect(ado)
    b = result['builds'][0]
    assert b['matches_reviewed_commit_and_repo'] is True and b['source_commit'] == COMMIT
    assert b['tests']['runs'][0]['passedTests'] == 9
    assert b['tests']['runs'][0]['incompleteTests'] is None  # unknown is not zero


def test_stale_or_wrong_repository_success_is_not_current_validation():
    ado = Ado(builds=[build(sourceVersion='b'*40), build(id=9, repository={'id': 'other'})])
    result = collect(ado)
    assert len(result['builds']) == 1
    assert result['builds'][0]['matches_reviewed_commit_and_repo'] is False
    assert ado.test_calls == []


def test_running_build_and_partial_result_are_preserved():
    row = collect(Ado(builds=[build(status='inProgress', result='partiallySucceeded')]))['builds'][0]
    assert row['status'] == 'inProgress' and row['result'] == 'partiallySucceeded'


def test_no_published_tests_and_permission_failure_are_unknown_not_passes():
    assert 'outcome unknown' in collect(Ado())['builds'][0]['tests']['availability']
    assert 'access denied' in collect(Ado(denied=True))['builds'][0]['tests']['availability']


def test_no_builds_and_inaccessible_builds_are_explicit():
    assert 'unknown' in collect(Ado(builds=[]))['availability']
    assert 'access denied' in collect(FakeAdo(fail={'builds'}))['availability']


def test_latest_rerun_is_not_hidden_by_an_older_success():
    result = collect(Ado(builds=[build(id=9, result='failed'), build(id=7)]))
    assert len(result['builds']) == 1 and result['builds'][0]['result'] == 'failed'


def test_missing_repository_or_commit_does_not_confirm_validation():
    for candidate in (build(repository={}), build(sourceVersion=None)):
        ado = Ado(builds=[candidate])
        assert collect(ado)['builds'][0]['matches_reviewed_commit_and_repo'] is False
        assert ado.test_calls == []


def test_evidence_reaches_discovery_integration_verification_and_refutation(monkeypatch):
    from pr_support import finding
    ado = Ado()
    model = FakePrModel({'scripts/report.py': [finding(17)]})
    result = pr_review.PullRequestReviewService(ado, model).review('proj', 'repo', 7)
    prompts = [u for _, u in model.calls]
    for kind in ('file', 'verify', 'refute'):
        assert all('Observed build/test evidence' in u and COMMIT in u for u in model.calls_of(kind))
    assert any('All changed paths' in u and 'Observed build/test evidence' in u for u in prompts)
    assert 'the build checks that' not in pr_review.FILE_SYSTEM
    assert any('missing evidence is treated as unknown' in n for n in result['notes'])
