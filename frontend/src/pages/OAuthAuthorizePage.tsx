import { useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'

const SCOPE_LABELS: Record<string, { title: string; detail: string; highRisk?: boolean }> = {
  'projects:read': { title: '讀取專案', detail: '查看可使用的專案與進度。' },
  'rows:read': { title: '讀取標注資料', detail: '查看資料列、內容與既有分類結果。' },
  'tasks:read': { title: '讀取分類任務', detail: '查看目前與歷史任務。' },
  'tasks:run': { title: '執行分類任務', detail: '領取、處理並提交 MCP 分類任務。' },
  'rows:write': { title: '修改資料列', detail: '寫入人工修正、備註與未確定狀態。', highRisk: true },
  'reviews:approve': { title: '核准單筆資料', detail: '將單一資料列標記為已核准。', highRisk: true },
  'reviews:batch_approve': { title: '批次核准資料', detail: '一次核准多筆資料，請只在必要時授權。', highRisk: true },
  offline_access: { title: '維持連線', detail: '允許以 refresh token 續期，不必頻繁重新登入。' },
}
const DEFAULT_SCOPES = new Set(['projects:read', 'rows:read', 'tasks:read', 'tasks:run', 'offline_access'])

export default function OAuthAuthorizePage() {
  const { user, loading } = useAuth()
  const location = useLocation()
  const params = useMemo(() => new URLSearchParams(location.search), [location.search])
  const clientId = params.get('client_id') || ''
  const redirectUri = params.get('redirect_uri') || ''
  const requestedScope = params.get('scope') || ''
  const resource = params.get('resource') || ''
  const state = params.get('state') || ''
  const codeChallenge = params.get('code_challenge') || ''
  const codeChallengeMethod = params.get('code_challenge_method') || ''
  const [clientName, setClientName] = useState('MCP App')
  const [requestedScopes, setRequestedScopes] = useState<string[]>([])
  const [approved, setApproved] = useState<Set<string>>(new Set())
  const [projectInput, setProjectInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!clientId || !redirectUri || !codeChallenge || codeChallengeMethod !== 'S256' || params.get('response_type') !== 'code') {
      setError('這個 OAuth 授權請求不完整或不支援。')
      return
    }
    api.getOAuthAuthorizationInfo(clientId, redirectUri, requestedScope).then(info => {
      setClientName(info.client_name)
      setRequestedScopes(info.requested_scopes)
      setApproved(new Set(info.requested_scopes.filter(scope => DEFAULT_SCOPES.has(scope))))
    }).catch(e => setError(e instanceof Error ? e.message : '無法驗證 MCP App'))
  }, [clientId, redirectUri, requestedScope, codeChallenge, codeChallengeMethod])

  if (loading) return <div className="min-h-screen grid place-items-center text-sm text-muted-foreground">載入中…</div>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />

  const toggle = (scope: string) => setApproved(previous => {
    const next = new Set(previous)
    next.has(scope) ? next.delete(scope) : next.add(scope)
    return next
  })
  const allow = async () => {
    setBusy(true); setError(null)
    try {
      const projectIds = projectInput.trim()
        ? projectInput.split(',').map(value => Number(value.trim())).filter(Number.isInteger).filter(value => value > 0)
        : []
      const result = await api.completeOAuthAuthorization({
        client_id: clientId, redirect_uri: redirectUri, code_challenge: codeChallenge,
        code_challenge_method: codeChallengeMethod, scope: requestedScope, resource,
        approved_scopes: Array.from(approved), project_ids: projectIds,
      })
      const callback = new URL(redirectUri)
      callback.searchParams.set('code', result.code)
      if (state) callback.searchParams.set('state', state)
      window.location.assign(callback.toString())
    } catch (e) { setError(e instanceof Error ? e.message : '授權失敗') }
    finally { setBusy(false) }
  }

  return <main className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center p-4">
    <section className="w-full max-w-xl rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-7 shadow-sm space-y-5">
      <div><p className="text-xs font-semibold tracking-wide text-violet-600">LLM-LABEL MCP</p><h1 className="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">授權 {clientName}</h1><p className="mt-2 text-sm text-gray-500 dark:text-gray-400">以 {user.username} 的平台帳號建立獨立、可撤銷的 MCP 連線。</p></div>
      <div className="space-y-2">{requestedScopes.map(scope => {
        const detail = SCOPE_LABELS[scope]
        return <label key={scope} className="flex gap-3 rounded-lg border border-gray-200 dark:border-gray-700 p-3 cursor-pointer">
          <input type="checkbox" checked={approved.has(scope)} onChange={() => toggle(scope)} className="mt-1" />
          <span><span className="text-sm font-medium text-gray-900 dark:text-gray-100">{detail?.title || scope}{detail?.highRisk ? ' · 需明確授權' : ''}</span><span className="block text-xs text-gray-500 dark:text-gray-400 mt-0.5">{detail?.detail}</span></span>
        </label>
      })}</div>
      <div><label className="block text-sm font-medium text-gray-700 dark:text-gray-300">限制可存取專案（選填）</label><input value={projectInput} onChange={e => setProjectInput(e.target.value)} placeholder="例如：12, 34；留空代表依已授權 scope 存取所有專案" className="mt-1.5 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 px-3 py-2 text-sm" /></div>
      {error && <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">{error}</p>}
      <div className="flex justify-end gap-3"><button onClick={() => window.close()} className="rounded-lg px-4 py-2 text-sm text-gray-600">取消</button><button disabled={busy || approved.size === 0 || !!error} onClick={allow} className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? '授權中…' : '允許並連線'}</button></div>
    </section>
  </main>
}
