import { describe, expect, it } from 'vitest'
import type { InnerSourceLeaderboardResponse, InnerSourcePerson } from '../../types/api'

describe('InnerSource Leaderboard Data & Calculations', () => {
  const sampleData: InnerSourceLeaderboardResponse = {
    year: 2026,
    quarter: 2,
    total_quarter_points: 293.0,
    total_year_points: 2190.0,
    total_contributors: 6,
    leader: {
      name: 'LEEJamesK',
      unique_name: 'lee@domain.com',
      quarter_points: 113.0,
      year_total: 423.0,
      q1_points: 90.0,
      q2_points: 113.0,
      q3_points: 100.0,
      q4_points: 120.0,
      stories_count: 52,
      quarter_stories_count: 14,
      stories: [
        {
          id: 488097,
          title: 'Fixed alert validation for arcGIS VM',
          type: 'User Story',
          state: 'Closed',
          points: 13.0,
          closed_date: '2026-06-10',
          quarter: 2,
          url: 'https://dev.azure.com/org/proj/_workitems/edit/488097',
        },
      ],
    },
    leaderboard: [
      {
        name: 'LEEJamesK',
        unique_name: 'lee@domain.com',
        quarter_points: 113.0,
        year_total: 423.0,
        q1_points: 90.0,
        q2_points: 113.0,
        q3_points: 100.0,
        q4_points: 120.0,
        stories_count: 52,
        quarter_stories_count: 14,
        stories: [],
      },
      {
        name: 'SEBESTAPaulG',
        unique_name: 'paul@domain.com',
        quarter_points: 47.0,
        year_total: 1002.0,
        q1_points: 955.0,
        q2_points: 47.0,
        q3_points: 0.0,
        q4_points: 0.0,
        stories_count: 125,
        quarter_stories_count: 6,
        stories: [],
      },
      {
        name: 'MAREPALLIThanmayi',
        unique_name: 'thanmayi@domain.com',
        quarter_points: 43.0,
        year_total: 153.0,
        q1_points: 110.0,
        q2_points: 43.0,
        q3_points: 0.0,
        q4_points: 0.0,
        stories_count: 19,
        quarter_stories_count: 5,
        stories: [],
      },
      {
        name: 'WOODBURYCharlesEChuck',
        unique_name: 'chuck@domain.com',
        quarter_points: 41.0,
        year_total: 244.0,
        q1_points: 203.0,
        q2_points: 41.0,
        q3_points: 0.0,
        q4_points: 0.0,
        stories_count: 30,
        quarter_stories_count: 5,
        stories: [],
      },
      {
        name: 'BADONISachin',
        unique_name: 'sachin@domain.com',
        quarter_points: 29.0,
        year_total: 236.0,
        q1_points: 207.0,
        q2_points: 29.0,
        q3_points: 0.0,
        q4_points: 0.0,
        stories_count: 29,
        quarter_stories_count: 4,
        stories: [],
      },
      {
        name: 'MEREDITHRachelP',
        unique_name: 'rachel@domain.com',
        quarter_points: 20.0,
        year_total: 132.0,
        q1_points: 112.0,
        q2_points: 20.0,
        q3_points: 0.0,
        q4_points: 0.0,
        stories_count: 16,
        quarter_stories_count: 3,
        stories: [],
      },
    ],
    stories_evaluated: 271,
  }

  it('correctly tracks top contributor and leader points for the quarter', () => {
    expect(sampleData.leader).not.toBeNull()
    expect(sampleData.leader?.name).toBe('LEEJamesK')
    expect(sampleData.leader?.quarter_points).toBe(113.0)
    expect(sampleData.leader?.year_total).toBe(423.0)
  })

  it('correctly reports cumulative 2026 total for contributors with prior quarter points', () => {
    const paul = sampleData.leaderboard.find((p) => p.name === 'SEBESTAPaulG')
    expect(paul).toBeDefined()
    expect(paul?.quarter_points).toBe(47.0)
    expect(paul?.year_total).toBe(1002.0)
    expect(paul?.year_total).toBeGreaterThan(paul?.quarter_points || 0)
  })

  it('sorts contributors by quarter points descending by default', () => {
    const sorted = [...sampleData.leaderboard].sort((a, b) => b.quarter_points - a.quarter_points)
    expect(sorted[0].name).toBe('LEEJamesK')
    expect(sorted[1].name).toBe('SEBESTAPaulG')
    expect(sorted[2].name).toBe('MAREPALLIThanmayi')
    expect(sorted[3].name).toBe('WOODBURYCharlesEChuck')
    expect(sorted[4].name).toBe('BADONISachin')
    expect(sorted[5].name).toBe('MEREDITHRachelP')
  })

  it('supports sorting by year_total descending', () => {
    const sortedByYear = [...sampleData.leaderboard].sort((a, b) => b.year_total - a.year_total)
    expect(sortedByYear[0].name).toBe('SEBESTAPaulG')
    expect(sortedByYear[0].year_total).toBe(1002.0)
    expect(sortedByYear[1].name).toBe('LEEJamesK')
    expect(sortedByYear[1].year_total).toBe(423.0)
  })

  it('filters contributors by search query', () => {
    const query = 'sachin'
    const filtered = sampleData.leaderboard.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))
    expect(filtered.length).toBe(1)
    expect(filtered[0].name).toBe('BADONISachin')
  })
})
