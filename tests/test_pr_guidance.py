import pytest

from app.services.pr_diff import build_view
from app.services.pr_guidance import AZURE_PIPELINES_GUIDE, CLOUD_OPERATIONS_GUIDE, TYPESCRIPT_GUIDE, focused_guides, is_azure_pipeline
from app.services import pr_review
from pr_support import FakePrModel


@pytest.mark.parametrize('path,text', [
    ('azure-pipelines.yml', 'trigger: [main]'),
    ('azure-pipelines/templates/vars.yml', 'variables: []'),
    ('.azure-pipelines/deploy.yaml', 'parameters: []'),
    ('templates/build.yml', 'jobs:\n- job: Build\n  steps: []'),
    ('ci/check.yml', 'steps:\n- task: AzureCLI@2'),
    ('ci/check.yml', 'stages:\n- stage: Release'),
])
def test_azure_pipeline_entry_points_and_templates_are_recognized(path, text):
    assert is_azure_pipeline(path, text)
    assert AZURE_PIPELINES_GUIDE in focused_guides('YAML', path, text)


@pytest.mark.parametrize('path,text', [
    ('k8s/deploy.yml', 'apiVersion: apps/v1\nkind: Deployment\nspec: {}'),
    ('.github/workflows/ci.yml', 'jobs:\n  test:\n    steps:\n    - run: echo hi'),
    ('settings.yml', 'region: westus\nsubscription: example'),
    ('playbook.yml', '- hosts: all\n  tasks: []'),
    ('config.yml', 'jobs:\n  worker: 2'),
    ('config.yml', 'jobs: [nightly, daily]'),
])
def test_unrelated_yaml_does_not_get_azure_pipeline_rules(path, text):
    assert not is_azure_pipeline(path, text)
    assert focused_guides('YAML', path, text) == []


@pytest.mark.parametrize('language,path,text', [
    ('Python', 'scripts/cloud/cleanup.py', 'delete_all()'),
    ('PowerShell', 'scripts/status.ps1', 'Get-AzResource -Name $Name'),
    ('Shell', 'scripts/clean.sh', 'az group delete --name "$group"'),
    ('Python', 'worker.py', 'from azure.identity import DefaultAzureCredential'),
])
def test_cloud_guidance_is_selected_by_operations_path_or_actual_api(language, path, text):
    assert CLOUD_OPERATIONS_GUIDE in focused_guides(language, path, text)


def test_generic_script_is_not_mistaken_for_cloud_operations():
    assert focused_guides('Python', 'scripts/math.py', 'def total(xs): return sum(xs)') == []


@pytest.mark.parametrize('language', ['TypeScript', 'TypeScript (React)', 'JavaScript', 'JavaScript (React)'])
def test_ui_guidance_in_actual_file_review(language):
    view = build_view('src/View.tsx', language, 'add', '', 'const count = data.length;\n')
    model = FakePrModel()
    pr_review.review_file(model, view, {'title': 'Count', 'description': ''}, [])
    assert TYPESCRIPT_GUIDE in model.system_of('file')[0]


def test_pipeline_guidance_reaches_file_review_without_special_caller_setup():
    view = build_view('azure-pipelines.yml', 'YAML', 'add', '', 'steps:\n- script: echo ok\n')
    view.new_text = 'steps:\n- script: echo ok\n'
    model = FakePrModel()
    pr_review.review_file(model, view, {'title': 'CI', 'description': ''}, [])
    assert AZURE_PIPELINES_GUIDE in model.system_of('file')[0]
