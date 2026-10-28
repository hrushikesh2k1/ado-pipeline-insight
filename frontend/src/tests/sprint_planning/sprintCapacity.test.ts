import { afterEach, expect, it, vi } from 'vitest'
import { availableCapacityDays, capacityForPerson, capacityStorageKey, loadCapacityMembers, mergeCapacityMembers, sprintWorkingDays, totalCapacityHours, velocityCapacityInput, withSavedCapacity } from '../../utils/sprintCapacity'
import { velocityContext } from './planningFixtures'

afterEach(() => vi.unstubAllGlobals())

it('preserves zero capacity and uses the same hours calculation as the Capacity tab', () => {
  const member = velocityContext().upcoming_capacity!.members[0]
  expect(totalCapacityHours(10, { ...member, days_off: 2, capacity_per_day: 6 })).toBe(48)
  expect(totalCapacityHours(10, { ...member, capacity_per_day: 0 })).toBe(0)
  expect(totalCapacityHours(10, { ...member, days_off: 12 })).toBe(0)
  expect(availableCapacityDays(0, 0)).toBe(0)
  expect(sprintWorkingDays(0, '2026-10-05', '2026-10-16')).toBe(0)
  expect(sprintWorkingDays(null, '2026-10-05', '2026-10-16')).toBe(10)
  expect(sprintWorkingDays(null, null, null)).toBeNull()
})

it('isolates scoped overrides and overlays both relevant sprint snapshots', () => {
  const context = velocityContext()
  const saved = [{ ...context.upcoming_capacity!.members[0], days_off: 3, capacity_per_day: 6 }]
  const data: Record<string, string> = {
    [capacityStorageKey('Org', 'Demo', 'alpha', 's3')]: JSON.stringify(saved),
    [capacityStorageKey('Org', 'Demo', 'alpha', 's1')]: JSON.stringify([{ ...saved[0], days_off: 1 }]),
  }
  vi.stubGlobal('localStorage', { getItem: (key: string) => data[key] ?? null })
  expect(loadCapacityMembers('Other', 'Demo', 'alpha', 's3')).toEqual([])
  const resolved = withSavedCapacity(context, 'Org', 'Demo', 'alpha')
  expect(resolved.upcoming_capacity!.members[0].days_off).toBe(3)
  const payload = velocityCapacityInput(resolved)
  expect(payload.previous_members[0].days_off).toBe(1)
  expect(payload.upcoming_members[0].capacity_per_day).toBe(6)
  expect(payload.previous_iteration_id).toBe('s1')
  expect(context.upcoming_capacity!.members[0].days_off).toBe(0)
})

it('can read existing Capacity-tab settings and reports malformed settings instead of inventing defaults', () => {
  const member = velocityContext().upcoming_capacity!.members[0]
  vi.stubGlobal('localStorage', { getItem: (key: string) => key === 'ado_sprint_capacity_alpha_s3' ? JSON.stringify([member]) : null })
  expect(loadCapacityMembers('org', 'Demo', 'alpha', 's3')).toEqual([member])
  vi.stubGlobal('localStorage', { getItem: () => JSON.stringify([{ ...member, days_off: 'invalid' }]) })
  expect(() => loadCapacityMembers('org', 'Demo', 'alpha', 's3')).toThrow('invalid')
})

it('matches identities exactly and does not use a conflicting or ambiguous name', () => {
  const context = velocityContext()
  const snapshot = context.upcoming_capacity!
  expect(capacityForPerson(snapshot, { name: 'Renamed', unique_name: 'ava@test' })?.name).toBe('Ava')
  expect(capacityForPerson(snapshot, { name: 'Ava', unique_name: 'other@test' })).toBeNull()
  snapshot.members.push({ ...snapshot.members[0], unique_name: 'other@test' })
  expect(capacityForPerson(snapshot, { name: 'Ava', unique_name: '' })).toBeNull()
  expect(capacityForPerson(null, { name: 'Ava', unique_name: 'ava@test' })).toBeNull()
})

it('shares merge behavior while preserving actual ADO identity for manually saved overrides', () => {
  const member = velocityContext().upcoming_capacity!.members[0]
  const merged = mergeCapacityMembers([member], [{ ...member, id: 'legacy-id', unique_name: null, days_off: 2 }])
  expect(merged).toHaveLength(1)
  expect(merged[0]).toMatchObject({ id: 'ava', unique_name: 'ava@test', days_off: 2 })
})

it('keeps different people with the same display name separate when applying overrides', () => {
  const member = velocityContext().upcoming_capacity!.members[0]
  const other = { ...member, id: 'other', unique_name: 'other@test' }
  const merged = mergeCapacityMembers([member, other], [{ ...other, days_off: 4 }])
  expect(merged).toHaveLength(2)
  expect(merged.find(m => m.unique_name === 'ava@test')?.days_off).toBe(0)
  expect(merged.find(m => m.unique_name === 'other@test')?.days_off).toBe(4)
})
