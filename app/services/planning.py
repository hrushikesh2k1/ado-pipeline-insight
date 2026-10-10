"""Planning proposals only. No Azure DevOps writes or outbound email calls."""
from datetime import datetime, timezone, timedelta
import base64
import hashlib
import hmac
import json
import os
import re
from pydantic import BaseModel, Field, model_validator
from app.services.snapshot_store import SnapshotStore

TEST_EMAIL = 'hrushikeshboora@gmail.com'
EMAIL = re.compile(r'[^\s@;,<>]+@[^\s@;,<>]+\.[^\s@;,<>]+')

class ReminderSettings(BaseModel):
    planning_day: int = Field(7, ge=1, le=28)
    reminder_days: list[int] = Field(default_factory=lambda:[1,3,5], min_length=1, max_length=3)
    period: str = 'current'
    leave_recipients: list[str] = Field(default_factory=list, max_length=500)
    lead_emails: list[str] = Field(default_factory=list, max_length=100)
    leave_automatic: bool = False
    priorities_automatic: bool = False
    @model_validator(mode='after')
    def validate_settings(self):
        if self.period not in ('current','next') or any(d < 1 or d >= self.planning_day for d in self.reminder_days):
            raise ValueError('Reminder dates must precede planning day; period must be current or next.')
        if any(not EMAIL.fullmatch(e) for e in self.lead_emails):
            raise ValueError('Enter valid lead email addresses.')
        if self.leave_automatic or self.priorities_automatic:
            raise ValueError('Automatic sending is unavailable until an approved email provider is configured.')
        return self

class LeavePlan(BaseModel):
    start: str = Field(max_length=10)
    end: str = Field(max_length=10)
    hours_per_day: float | None = Field(None, gt=0, le=24)
    tentative: bool = True
    @model_validator(mode='after')
    def dates(self):
        from datetime import date
        if date.fromisoformat(self.end) < date.fromisoformat(self.start):
            raise ValueError('Leave end precedes start.')
        return self

class Submission(BaseModel):
    person_id: str = Field(min_length=1,max_length=256)
    no_leave: bool = False
    leave: list[LeavePlan] = Field(default_factory=list,max_length=100)
    priorities: list[dict] = Field(default_factory=list,max_length=100)
    @model_validator(mode='after')
    def validate_submission(self):
        if self.no_leave and self.leave:
            raise ValueError('No leave cannot be combined with leave dates.')
        for priority in self.priorities:
            if not str(priority.get('outcome','')).strip() or not isinstance(priority.get('rank'),int) or priority['rank'] < 1:
                raise ValueError('Each priority needs an outcome and positive rank.')
        if any(not isinstance(i,int) or i<=0 for p in self.priorities for i in p.get('work_item_ids',[])):
            raise ValueError('Work item IDs must be positive integers.')
        return self


def signed_link(scope, person_id, kind, iteration=None):
    secret = os.getenv('PLANNING_LINK_SECRET')
    if not secret:
        raise ValueError('Configure PLANNING_LINK_SECRET before creating response links.')
    if kind not in ('leave', 'priorities') or len(scope) != 4:
        raise ValueError('Invalid response request.')
    payload = {'scope':scope, 'person_id':person_id, 'kind':kind, 'test_mode':True, 'expires':int((datetime.now(timezone.utc)+timedelta(days=45)).timestamp())}
    if iteration:
        payload['sprint'] = iteration.get('name')
        payload['period'] = iteration.get('attributes', {})
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    sig = hmac.new(secret.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+'.'+sig


def verify_link(token):
    secret = os.getenv('PLANNING_LINK_SECRET')
    if not secret:
        raise ValueError('Response links are not configured.')
    try:
        raw,sig = token.split('.')
        expected = hmac.new(secret.encode(),raw.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig,expected):
            raise ValueError('Invalid response link.')
        data=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
        if not isinstance(data,dict) or not isinstance(data.get('scope'),list) or len(data['scope']) != 4 or any(not isinstance(v,str) or not v for v in data['scope']):
            raise ValueError('Invalid scope.')
        if data.get('kind') not in ('leave','priorities') or not data.get('test_mode'):
            raise ValueError('Only test response links are enabled.')
        if data['expires'] < datetime.now(timezone.utc).timestamp():
            raise ValueError('Response link has expired.')
        return data
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('Invalid or expired response link.') from exc


def read_state(scope):
    store = SnapshotStore()
    settings = store.read('planning-settings',scope[:3]) or ReminderSettings().model_dump()
    return {'settings':settings, 'test_mode':True,'test_recipient':TEST_EMAIL,
            'proposal':store.read('planning-proposal',scope)}


def save_settings(scope,settings):
    SnapshotStore().write('planning-settings',scope[:3],settings.model_dump())
    return read_state(scope)


def save_submission(token,submission):
    link=verify_link(token)
    if submission.person_id != link['person_id']:
        raise ValueError('Response identity does not match the link.')
    if link['kind']=='leave' and (submission.priorities or not(submission.no_leave or submission.leave)):
        raise ValueError('Provide leave dates or explicitly confirm no leave.')
    if link['kind']=='priorities' and (submission.leave or not submission.priorities):
        raise ValueError('Provide at least one priority.')
    # One blob per recipient and request type avoids overwriting simultaneous responses.
    scope=link['scope']+[link['kind'],link['person_id']]
    value=submission.model_dump()
    value['test_mode']=True
    value['submitted_at']=datetime.now(timezone.utc).isoformat()
    SnapshotStore().write('planning-response',scope,value)
    return {'saved':True,'submitted_at':value['submitted_at']}


def proposal(ado,scope,iteration):
    from app.services.board_views import capacity_view,backlog_view
    from app.services.deliverables import number
    from app.services.work_item_scope import parse_when
    from datetime import date
    state=read_state(scope);store=SnapshotStore();priorities=[];warnings=[]
    for email in state['settings']['lead_emails']:
        response=store.read('planning-response',scope+['priorities',email])
        if response:priorities.extend(response['priorities'])
        else:warnings.append(f'Priority response pending: {email}')
    priorities.sort(key=lambda p:p['rank'])
    capacity=capacity_view(ado,scope[1],scope[2],scope[3]);scenarios=[]
    first=parse_when(iteration['attributes'].get('startDate'));last=parse_when(iteration['attributes'].get('finishDate'))
    weekdays=['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
    for member in capacity['people']:
        who=member['person'];base=member['available_hours']
        response=store.read('planning-response',scope+['leave',who['id']])
        if not response:warnings.append(f'Leave response pending: {who["name"]}; capacity is provisional.')
        daily=sum(number(a.get('capacityPerDay')) or 0 for a in member['activities'])
        confirmed=tentative=0
        if response:
            day=first.date()
            while day<=last.date():
                existing=member['days_off']+capacity['team_days_off']
                absent=any(parse_when(off['start']).date()<=day<=parse_when(off['end']).date() for off in existing)
                if weekdays[day.weekday()] in [d.lower() for d in capacity['working_days']] and not absent:
                    c=t=0
                    for leave in response['leave']:
                        if date.fromisoformat(leave['start'])<=day<=date.fromisoformat(leave['end']):
                            amount=min(daily,leave['hours_per_day'] if leave['hours_per_day'] is not None else daily)
                            if leave['tentative']:t=max(t,amount)
                            else:c=max(c,amount)
                    confirmed+=c;tentative+=max(c,t)-c
                day+=timedelta(days=1)
        scenarios.append({'id':who['id'],'name':who['name'],'base':base,'confirmed':max(0,base-confirmed) if base is not None else None,'tentative':max(0,base-confirmed-tentative) if base is not None else None})
    backlog = backlog_view(ado,scope[1],scope[2])
    index = {i['id']:i for i in backlog['items']}
    items = []
    seen = set()
    budgets = {c['id']:c['tentative'] for c in scenarios}
    by_id = {c['id']:c for c in scenarios}
    from app.services.deliverables import identity
    if not state['settings']['lead_emails']:
        warnings.append('No lead recipients are configured. Provide priorities before generating a useful scope proposal.')
    warnings.append('Skills and dependency readiness require team review. Capacity-based suggestions are not approved assignments.')
    for priority in priorities:
        requested = priority.get('work_item_ids', [])
        if not requested:
            warnings.append(f"Priority '{priority['outcome']}' has no linked work items. Add explicit IDs; no scope is inferred from a vague outcome.")
        for item_id in requested:
            if item_id not in index:
                warnings.append(f'Priority references item {item_id}, which is not in the current team backlog.')
                continue
            if item_id in seen:
                continue
            seen.add(item_id)
            raw = index[item_id]
            fields = raw['fields']
            owner = identity(fields.get('System.AssignedTo'))
            hours = number(fields.get('Microsoft.VSTS.Scheduling.RemainingWork'))
            if hours is None:
                hours = number(fields.get('Microsoft.VSTS.Scheduling.OriginalEstimate'))
            dependencies = [int(r['url'].rstrip('/').split('/')[-1]) for r in raw.get('relations', [])
                            if r.get('rel') == 'System.LinkTypes.Dependency-Reverse' and str(r.get('url','')).rstrip('/').split('/')[-1].isdigit()]
            suggestion = by_id.get(owner['id'])
            reason = 'Retain the Azure DevOps owner; estimates, skills and dependencies need team review.'
            if hours is not None and not dependencies:
                if suggestion and budgets.get(suggestion['id']) is not None and budgets[suggestion['id']] >= hours:
                    reason = 'Existing owner fits the available capacity including tentative leave; skills require confirmation.'
                else:
                    candidates = [c for c in scenarios if budgets[c['id']] is not None and budgets[c['id']] >= hours]
                    suggestion = max(candidates,key=lambda c:budgets[c['id']]) if candidates else None
                    reason = ('Capacity-based suggestion using confirmed and tentative leave; skills and ownership must be approved.'
                              if suggestion else 'No member has sufficient verified remaining capacity for this estimate.')
                if suggestion:
                    budgets[suggestion['id']] -= hours
            elif dependencies:
                reason = 'Predecessor dependencies must be checked before commitment; current owner is shown for review.'
                warnings.append(f'#{item_id}: verify predecessor item(s) {", ".join(map(str,dependencies))}.')
            else:
                warnings.append(f'#{item_id}: no hour estimate. Story points are not converted to hours; capacity fit is unverified.')
            items.append({'id':item_id,'title':fields.get('System.Title'),'rank':priority['rank'],
                          'priority_outcome':priority['outcome'],'hours':hours,
                          'person':suggestion['name'] if suggestion else (owner['name'] if owner['id'] != 'unassigned' else None),
                          'person_id':suggestion['id'] if suggestion else owner['id'],
                          'original_owner':owner['name'],'dependencies':dependencies,'reason':reason,'approval_required':True})
    for cap in scenarios:
        assigned = sum(i['hours'] or 0 for i in items if i['person_id'] == cap['id'])
        cap['proposed_hours'] = assigned
        cap['remaining_after_proposal'] = max(0,cap['tentative']-assigned) if cap['tentative'] is not None else None
        if cap['confirmed'] is not None and assigned > cap['confirmed']:
            warnings.append(f'{cap["name"]}: proposed work exceeds confirmed capacity.')
    result = {'generated_at':datetime.now(timezone.utc).isoformat(),
              'message':'Priority-ordered proposal using capacity and leave scenarios. All suggestions require approval. No Azure DevOps changes made.',
              'items':items,'capacity':scenarios,'warnings':warnings,'test_mode':True}
    store.write('planning-proposal',scope,result)
    return result
