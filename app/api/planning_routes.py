from fastapi import APIRouter, Query, Header, HTTPException
from core.ado_client import AzureDevOpsClient
from core.validation import validate_organization,validate_project
from app.services.planning import ReminderSettings, Submission, read_state,save_settings,signed_link,verify_link,save_submission,TEST_EMAIL
from app.services.team_people import team_people
from app.services.snapshot_store import SnapshotStore

router=APIRouter(prefix='/api/v1/planning',tags=['planning'])

def context(organization,project,team,iteration_id,pat):
    from app.api.routes import _resolve_pat
    org=validate_organization(organization);proj=validate_project(project)
    ado=AzureDevOpsClient(org,_resolve_pat(org,pat))
    iteration=ado.get_team_iteration(proj,team,iteration_id)
    return ado,[org,proj,team,iteration_id],iteration

@router.get('')
def get_planning(organization:str,project:str,team:str,iteration_id:str,x_ado_pat:str|None=Header(None,alias='X-ADO-PAT')):
    try:
        ado,scope,iteration=context(organization,project,team,iteration_id,x_ado_pat)
        state=read_state(scope);members=team_people(ado,project,team)
        responses={}
        for kind,people in [('leave',[m['id'] for m in members]),('priorities',state['settings']['lead_emails'])]:
            for person in people:
                value=SnapshotStore().read('planning-response',scope+[kind,person])
                if value: responses[kind+':'+person]=value
        return {**state,'members':members,'responses':responses,'iteration':iteration,'automatic_available':False}
    except ValueError as exc: raise HTTPException(422,str(exc))
    except Exception as exc:
        from app.api.routes import _unavailable
        raise _unavailable(exc)

@router.put('/settings')
def put_settings(settings:ReminderSettings,organization:str,project:str,team:str,iteration_id:str,x_ado_pat:str|None=Header(None,alias='X-ADO-PAT')):
    try:
        ado,scope,_=context(organization,project,team,iteration_id,x_ado_pat)
        valid={m['id'] for m in team_people(ado,project,team)}
        if not set(settings.leave_recipients)<=valid: raise ValueError('Select members of the current team.')
        return save_settings(scope,settings)
    except ValueError as exc: raise HTTPException(422,str(exc))
    except Exception as exc:
        from app.api.routes import _unavailable
        raise _unavailable(exc)

@router.post('/draft')
def draft(kind:str,person_id:str,organization:str,project:str,team:str,iteration_id:str,x_ado_pat:str|None=Header(None,alias='X-ADO-PAT')):
    try:
        ado,scope,iteration=context(organization,project,team,iteration_id,x_ado_pat)
        state=read_state(scope)
        members=team_people(ado,project,team)
        if kind=='leave':
            people={m['id']:m for m in members}
            if person_id not in state['settings']['leave_recipients'] or person_id not in people: raise ValueError('Choose a configured team recipient.')
            who=people[person_id]['name']
        elif kind=='priorities':
            if person_id not in state['settings']['lead_emails']: raise ValueError('Choose a configured lead.')
            who=person_id
        else: raise ValueError('Unknown reminder type.')
        token=signed_link(scope,person_id,kind,iteration)
        return {'to':[TEST_EMAIL],'intended_person':who,'token':token,'sprint':iteration['name'],'kind':kind,'test_mode':True}
    except ValueError as exc: raise HTTPException(422,str(exc))
    except Exception as exc:
        from app.api.routes import _unavailable
        raise _unavailable(exc)

@router.get('/response')
def get_response(token:str=Query(...,max_length=4096)):
    try:
        link=verify_link(token)
        return {**link,'existing':SnapshotStore().read('planning-response',link['scope']+[link['kind'],link['person_id']])}
    except ValueError as exc: raise HTTPException(422,str(exc))

@router.post('/response')
def post_response(submission:Submission,token:str=Query(...,max_length=4096)):
    try: return save_submission(token,submission)
    except ValueError as exc: raise HTTPException(422,str(exc))

@router.get('/board-view')
def board_view(view:str,organization:str,project:str,team:str,iteration_id:str,level:str|None=None,x_ado_pat:str|None=Header(None,alias='X-ADO-PAT')):
    from app.services.board_views import capacity_view,backlog_view,analytics_view
    try:
        ado,_,_=context(organization,project,team,iteration_id,x_ado_pat)
        if view=='capacity':return capacity_view(ado,project,team,iteration_id)
        if view=='backlog':return backlog_view(ado,project,team,level)
        if view=='analytics':return analytics_view(ado,project,team,iteration_id)
        raise ValueError('Unknown board view.')
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception as exc:
        from app.api.routes import _unavailable
        raise _unavailable(exc)

@router.post('/proposal')
def generate_proposal(organization:str,project:str,team:str,iteration_id:str,x_ado_pat:str|None=Header(None,alias='X-ADO-PAT')):
    from app.services.planning import proposal
    try:
        ado,scope,iteration=context(organization,project,team,iteration_id,x_ado_pat)
        return proposal(ado,scope,iteration)
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception as exc:
        from app.api.routes import _unavailable
        raise _unavailable(exc)
