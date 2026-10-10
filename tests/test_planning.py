import pytest
from app.services.snapshot_store import SnapshotStore
from app.services.planning import ReminderSettings,Submission,signed_link,verify_link,save_submission,proposal
from unittest.mock import patch

def test_storage_scoped_and_persistent(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path))
    store=SnapshotStore();store.write('deliverables',['org','team-a'],{'hours':8})
    assert SnapshotStore().read('deliverables',['org','team-a'])=={'hours':8}
    assert store.read('deliverables',['org','team-b']) is None

def test_unconfigured_storage_fails(monkeypatch):
    monkeypatch.delenv('REPORT_STORAGE_DIR',raising=False);monkeypatch.delenv('REPORT_STORAGE_ACCOUNT_URL',raising=False)
    with pytest.raises(ValueError):SnapshotStore().write('x',[],{})

def test_manual_only_settings():
    with pytest.raises(ValueError):ReminderSettings(leave_automatic=True)
    with pytest.raises(ValueError):ReminderSettings(reminder_days=[8])
    with pytest.raises(ValueError):ReminderSettings(lead_emails=['not-an-email'])

def test_signed_response_scope(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path));monkeypatch.setenv('PLANNING_LINK_SECRET','test-secret')
    token=signed_link(['org','project','team','sprint'],'alice','leave')
    assert verify_link(token)['person_id']=='alice'
    with pytest.raises(ValueError):verify_link(token+'x')
    with pytest.raises(ValueError):save_submission(token,Submission(person_id='bob',no_leave=True))
    save_submission(token,Submission(person_id='alice',no_leave=True))
    assert SnapshotStore().read('planning-response',['org','project','team','sprint','leave','alice'])['no_leave']
    with pytest.raises(ValueError):save_submission(token,Submission(person_id='alice'))

def test_proposal_leave_overlap_and_existing_days_off(tmp_path,monkeypatch):
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path))
    scope=['org','project','team','sprint'];store=SnapshotStore()
    store.write('planning-response',scope+['leave','alice'],{'leave':[{'start':'2026-09-01','end':'2026-09-03','tentative':False,'hours_per_day':None},{'start':'2026-09-02','end':'2026-09-04','tentative':True,'hours_per_day':4}]})
    cap={'people':[{'person':{'id':'alice','name':'Alice'},'available_hours':168,'activities':[{'capacityPerDay':8}],'days_off':[{'start':'2026-09-01','end':'2026-09-01'}]}],'working_days':['monday','tuesday','wednesday','thursday','friday'],'team_days_off':[]}
    iteration={'attributes':{'startDate':'2026-09-01','finishDate':'2026-09-30'}}
    with patch('app.services.board_views.capacity_view',return_value=cap),patch('app.services.board_views.backlog_view',return_value={'items':[]}):
        result=proposal(None,scope,iteration)
    assert result['capacity'][0]['confirmed']==152
    assert result['capacity'][0]['tentative']==148


def test_settings_are_per_team_responses_per_sprint(tmp_path,monkeypatch):
    from app.services.planning import save_settings,read_state
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path))
    settings=ReminderSettings(lead_emails=['lead@example.com'],leave_recipients=['alice'])
    save_settings(['org','project','team','sept'],settings)
    assert read_state(['org','project','team','oct'])['settings']['lead_emails']==['lead@example.com']
    assert read_state(['org','project','other-team','oct'])['settings']['lead_emails']==[]


def test_draft_is_always_test_recipient_and_response_roundtrip(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.api import planning_routes
    from app.services.planning import save_settings
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path))
    monkeypatch.setenv('PLANNING_LINK_SECRET','test-secret')
    scope=['org','project','team','sprint']
    iteration={'name':'September','attributes':{'startDate':'2026-09-01','finishDate':'2026-09-30'}}
    monkeypatch.setattr(planning_routes,'context',lambda *args:(None,scope,iteration))
    monkeypatch.setattr(planning_routes,'team_people',lambda *args:[{'id':'alice','name':'Alice','email':'alice@example.com'}])
    save_settings(scope,ReminderSettings(leave_recipients=['alice'],lead_emails=['lead@example.com']))
    client=TestClient(create_app())
    params={'organization':'org','project':'project','team':'team','iteration_id':'sprint','kind':'leave','person_id':'alice'}
    drafted=client.post('/api/v1/planning/draft',params=params)
    assert drafted.status_code==200
    data=drafted.json()
    assert data['to']==['hrushikeshboora@gmail.com']
    token=data['token']
    submitted=client.post('/api/v1/planning/response',params={'token':token},json={'person_id':'alice','no_leave':True})
    assert submitted.status_code==200
    read=client.get('/api/v1/planning/response',params={'token':token}).json()
    assert read['existing']['no_leave'] and read['test_mode'] and read['sprint']=='September'
    assert client.post('/api/v1/planning/draft',params={**params,'person_id':'other'}).status_code==422


def test_priority_proposal_uses_capacity_after_leave_and_never_writes_ado(tmp_path,monkeypatch):
    from app.services.planning import save_settings
    monkeypatch.setenv('REPORT_STORAGE_DIR',str(tmp_path))
    scope=['org','project','team','sprint'];store=SnapshotStore()
    save_settings(scope,ReminderSettings(lead_emails=['lead@example.com']))
    store.write('planning-response',scope+['priorities','lead@example.com'],{'priorities':[{'rank':1,'outcome':'Alerts','work_item_ids':[1,2]}]})
    cap={'people':[{'person':{'id':'alice','name':'Alice'},'available_hours':8,'activities':[{'capacityPerDay':8}],'days_off':[]}],
         'working_days':['monday','tuesday','wednesday','thursday','friday'],'team_days_off':[]}
    backlog={'items':[{'id':1,'fields':{'System.Title':'First alert','Microsoft.VSTS.Scheduling.OriginalEstimate':6}},
                      {'id':2,'fields':{'System.Title':'Second alert','Microsoft.VSTS.Scheduling.OriginalEstimate':6}}]}
    iteration={'attributes':{'startDate':'2026-09-01','finishDate':'2026-09-30'}}
    with patch('app.services.board_views.capacity_view',return_value=cap),patch('app.services.board_views.backlog_view',return_value=backlog):
        result=proposal(None,scope,iteration)
    assert result['items'][0]['person']=='Alice'
    assert result['items'][1]['person'] is None
    assert all(i['approval_required'] for i in result['items'])
    assert result['capacity'][0]['remaining_after_proposal']==2
    assert SnapshotStore().read('planning-proposal',scope)==result
