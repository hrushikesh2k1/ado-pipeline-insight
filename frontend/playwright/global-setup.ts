import { request, type FullConfig } from '@playwright/test'
import { mkdirSync } from 'node:fs'

/** Signs in once with QG_USERNAME / QG_PASSWORD (the app's built-in login) and saves the session for every spec. */
export default async function globalSetup(config: FullConfig) {
  const username = process.env.QG_USERNAME
  const password = process.env.QG_PASSWORD
  if (!username || !password) return
  const baseURL = config.projects[0].use.baseURL as string
  const ctx = await request.newContext({ baseURL })
  const res = await ctx.post('/api/v1/auth/login', { data: { username, password } })
  if (!res.ok()) throw new Error(`Sign-in as QG_USERNAME failed with HTTP ${res.status()}`)
  mkdirSync('./playwright/.auth', { recursive: true })
  await ctx.storageState({ path: './playwright/.auth/state.json' })
  await ctx.dispose()
}
