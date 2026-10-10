from app.services.board_views import capacity_view, backlog_view, analytics_view
from app.services.team_people import team_people

class Ado:
    organization='org'
    def get_team_iteration(self,*args):
        return {'name':'September','path':'Project\\September','attributes':{'startDate':'2026-09-01','finishDate':'2026-09-30'}}
    def get_team_settings(self,*args):
        return {'workingDays':['monday','tuesday','wednesday','thursday','friday']}
    def get_team_days_off(self,*args):
        return {'daysOff':[]}
    def get_iteration_capacity(self,*args):
        return {'teamMembers':[{'teamMember':{'id':'alice','displayName':'Alice'},'activities':[{'name':'Development','capacityPerDay':8}],
                               'daysOff':[{'start':'2026-09-07','end':'2026-09-08'}]}]}
    def get_team_field_values(self,*args):
        return {'values':[{'value':'Project\\Monitoring','includeChildren':True}]}
    def query_wiql(self,project,query,top):
        assert "[System.IterationPath] = 'Project\\September'" in query
        assert "[System.AreaPath] UNDER 'Project\\Monitoring'" in query
        assert 'ASOF' in query
        return [1,2]
    def get_work_items_batch(self,project,ids,as_of=None):
        assert as_of is not None
        return [{'id':1,'fields':{'Microsoft.VSTS.Scheduling.RemainingWork':8}}, {'id':2,'fields':{}}]


def test_capacity_160_is_22_weekdays_less_two_leave_days_times_eight():
    result=capacity_view(Ado(),'Project','Monitoring','sept')
    assert result['people'][0]['available_hours']==160
    assert result['people'][0]['available_days']==20
    assert result['people'][0]['daily_hours']==8
    assert result['source'].startswith('Azure DevOps')


def test_backlog_uses_native_order_and_levels(monkeypatch):
    import app.services.board_views as service
    def get(ado,project,team,path):
        if path=='backlogs':return {'value':[{'id':'requirements','type':'requirement','name':'Stories'}]}
        return {'workItems':[{'target':{'id':3}},{'target':{'id':1}},{'target':{'id':3}}]}
    monkeypatch.setattr(service,'team_get',get)
    ado=Ado()
    ado.get_work_items_batch=lambda project,ids:[{'id':1,'fields':{}},{'id':3,'fields':{}}]
    result=backlog_view(ado,'Project','Monitoring')
    assert [i['id'] for i in result['items']]==[3,1]
    assert result['selected_level']=='requirements'


def test_analytics_uses_matching_asof_scope_and_flags_missing_values():
    result=analytics_view(Ado(),'Project','Monitoring','sept')
    assert len(result['points'])==30
    assert result['points'][0]=={'date':'2026-09-01','remaining_hours':8,'tasks':2,'missing_remaining_work':1,'provisional':False}


def test_team_group_expands_without_group_name_in_missing_addresses():
    class Response:
        def __init__(self,data):self.data=data
        def raise_for_status(self):pass
        def json(self):return self.data
    class Session:
        def get(self,url,params,timeout):
            if 'identityIds' in params:
                return Response({'value':[{'members':[{'identityType':'Microsoft.IdentityModel.Claims.ClaimsIdentity','identifier':'alice'}]}]})
            return Response({'value':[{'id':'alice','providerDisplayName':'Alice','isContainer':False,
                                     'properties':{'Mail':{'$value':'alice@example.com'}}}]})
    ado=Ado();ado.session=Session()
    ado.list_team_members=lambda *args:[{'identity':{'id':'group','displayName':'CloudOps','isContainer':True}},
                                       {'identity':{'id':'alice','displayName':'Alice','uniqueName':'alice@example.com'}}]
    people=team_people(ado,'Project','Monitoring')
    assert people==[{'id':'alice','name':'Alice','email':'alice@example.com'}]


def test_empty_team_group_is_not_a_missing_person():
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'value':[{'members':[]}]}
    class Session:
        def get(self,*args,**kwargs):return Response()
    ado=Ado();ado.session=Session()
    ado.list_team_members=lambda *args:[{'identity':{'id':'group','displayName':'CloudOps','isContainer':True}}]
    assert team_people(ado,'Project','Monitoring')==[]
