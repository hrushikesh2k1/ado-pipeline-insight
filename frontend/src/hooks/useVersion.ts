import { useQuery } from '@tanstack/react-query'
import { api } from '../services/api'

/** The release the running backend reports (from the repo's VERSION file); never hardcoded in the UI. */
export function useVersion() {
  return useQuery({ queryKey: ['app-version'], queryFn: api.version, staleTime: Infinity, retry: false })
}
