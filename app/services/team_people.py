"""Expand team groups to individual identities; never treat a group name as an email."""
from urllib.parse import quote
from app.services.deliverables import identity

def team_people(ado, project, team):
    members = ado.list_team_members(project, team)
    people = {}
    pending = [m.get('identity', {}) for m in members]
    visited = set()
    while pending:
        raw = pending.pop()
        ident = raw.get('id') or raw.get('descriptor') or raw.get('uniqueName') or raw.get('displayName')
        if not ident:
            raise ValueError('A team identity has no verifiable identifier.')
        if ident in visited:
            continue
        visited.add(ident)
        if len(visited) > 5000:
            raise ValueError('Team membership exceeds the supported limit.')
        if raw.get('isDeletedInOrigin') or raw.get('isActive') is False:
            continue
        if raw.get('isContainer') or raw.get('isGroup') or str(raw.get('displayName', '')).startswith('[TEAM FOUNDATION]'):
            response = ado.session.get(f'https://vssps.dev.azure.com/{quote(ado.organization, safe="")}/_apis/identities', params={'identityIds': raw.get('id'), 'queryMembership': 'expanded', 'api-version': '7.1'}, timeout=30)
            response.raise_for_status()
            groups = response.json().get('value', [])
            descriptors = [d if isinstance(d,str) else d['identityType']+';'+d['identifier'] for group in groups for d in group.get('members', [])]
            if not groups:
                raise ValueError('Team group membership could not be expanded; verify Azure DevOps identity read access.')
            for offset in range(0, len(descriptors), 100):
                response = ado.session.get(f'https://vssps.dev.azure.com/{quote(ado.organization, safe="")}/_apis/identities', params={'descriptors': ','.join(descriptors[offset:offset+100]), 'api-version': '7.1'}, timeout=30)
                response.raise_for_status()
                resolved = response.json().get('value', [])
                if len(resolved) != len(descriptors[offset:offset+100]):
                    raise ValueError('Some team identities could not be resolved.')
                for member in resolved:
                    props = member.get('properties', {})
                    pending.append({**member, 'displayName': member.get('providerDisplayName'), 'uniqueName': props.get('Mail', {}).get('$value') or props.get('Account', {}).get('$value')})
        else:
            person = identity(raw)
            people[person['id']] = person
    return sorted(people.values(), key=lambda p:p['name'].lower())
