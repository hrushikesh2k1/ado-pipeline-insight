import {describe,expect,it} from 'vitest'
import {formatSeconds} from './utils'
describe('formatSeconds',()=>{
  it('formats seconds',()=>expect(formatSeconds(42)).toBe('42s'))
  it('formats minutes',()=>expect(formatSeconds(125)).toBe('2m 5s'))
  it('handles missing values',()=>expect(formatSeconds(null)).toBe('0s'))
})
