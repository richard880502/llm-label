const BASE = '/api'

export function getToken(): string | null {
  return localStorage.getItem('token')
}

export function clearToken(): void {
  localStorage.removeItem('token')
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (init?.headers) Object.assign(headers, init.headers)
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, { ...init, headers, cache: 'no-store' })

  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const text = await res.text()
      try { const j = JSON.parse(text); msg = j.detail || JSON.stringify(j) } catch { msg = text || msg }
    } catch { /* ignore */ }
    const err = new Error(msg) as Error & { status: number }
    err.status = res.status
    throw err
  }
  return res.json()
}

export interface Project {
  id: number; name: string; filename: string; created_at: string
  total_rows: number; approved: number; corrected: number; uncertain: number; pending: number
  annotation_instructions: string
}

export interface RowSummary {
  id: number; source_row_number: number; content: string; comment_content: string
  ai_relevance: string; ai_labels: string; ai_emotional_subtypes: string
  corrected_relevance: string | null; corrected_labels: string | null
  corrected_emotional_subtypes: string | null
  status: 'pending' | 'approved' | 'corrected' | 'uncertain'; reviewed_at: string | null
  llm_updated_at: string | null
  llm_disagreement: number
  llm_parse_failed: number
  reviewer_username: string | null
}

export interface LLMResult {
  slot: number; name: string; relevance: string | null; labels: string; subtypes: string; reason: string; updated_at: string
}

export interface LLMSlotConfig {
  slot: number; name: string; api_url: string; api_key: string; model: string
  prompt_template: string; examples_mode: string; examples_per_label: number; concurrency: number
  extra_body: string; has_api_key: boolean
}

export interface LegacyLLMConfig {
  api_url: string; api_key: string; model: string; prompt_template: string
  examples_mode: string; examples_per_label: number; has_api_key: boolean
}

export interface RowDetail extends RowSummary {
  ai_reason: string; reviewer_note: string | null; original_data: string
  llm_results: LLMResult[]; version: number
}

export interface RowsResponse {
  total: number | null; page: number; page_size: number; items: RowSummary[]
}

export interface Adjacent {
  prev_id: number | null; next_id: number | null; position: number | null; total: number | null
}

export interface RowUpdate {
  corrected_result?: AnnotationResult | null
  corrected_relevance?: string | null; corrected_labels?: string[]
  corrected_emotional_subtypes?: string[]; reviewer_note?: string; status?: string
  version?: number
}

export interface AnnotationResult {
  relevance?: string | null
  labels: string[]
  reason?: string
  metadata?: Record<string, unknown>
}

export interface PresenceEntry {
  username: string
  row_id: number
}

export interface User {
  id: number; username: string; role: string; created_at: string; is_active: number; email: string | null; totp_enabled: number
}

export interface AuditEntry {
  id: number
  username: string
  status: string | null
  relevance: string | null
  labels: string | null
  changed_at: string
}

export interface Task {
  id: number
  project_id: number
  slot: number | null
  status: 'pending' | 'waiting_for_agent' | 'running' | 'done' | 'failed' | 'cancelled'
  total: number
  processed: number
  failed: number
  created_at: string
  finished_at: string | null
  error: string | null
  execution_mode: 'api' | 'mcp'
  executor_name: string
  target: 'pending' | 'all' | 'parse_failed'
  created_by: string
  claimed_by: string
  last_activity_at: string | null
}

export interface ApiToken {
  id: number
  name: string
  token_prefix: string
  created_at: string
  last_used_at?: string | null
  token?: string
}

export interface McpOAuthConnection {
  id: number; client_name: string; scopes: string; project_ids: string
  created_at: string; last_used_at?: string | null
}

export const api = {
  // auth
  getAuthConfig: () => request<{ google_client_id: string }>('/auth/config'),
  googleLogin: (credential: string) =>
    request<{ token: string; username: string; role: string; requires_totp?: boolean; temp_token?: string }>('/auth/google', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential }),
    }),
  login: (username: string, password: string) =>
    request<{ token: string; username: string; role: string; requires_totp?: boolean; temp_token?: string }>('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  totpVerifyLogin: (code: string, temp_token: string) =>
    request<{ token: string; username: string; role: string }>('/auth/totp/verify-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, temp_token }),
    }),
  totpStatus: () => request<{ enabled: boolean }>('/auth/totp/status'),
  totpSetup: () => request<{ secret: string; uri: string }>('/auth/totp/setup', { method: 'POST' }),
  totpConfirm: (code: string) =>
    request('/auth/totp/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    }),
  totpDisable: () => request('/auth/totp', { method: 'DELETE' }),
  me: () => {
    if (!getToken()) return Promise.resolve(null) as Promise<{ username: string; role: string } | null>
    return request<{ username: string; role: string }>('/auth/me').catch(() => null)
  },
  changePassword: (current_password: string, new_password: string) =>
    request('/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password }),
    }),
  listApiTokens: () => request<ApiToken[]>('/auth/tokens'),
  createApiToken: (name: string) => request<ApiToken>('/auth/tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }),
  revokeApiToken: (id: number) => request<{ ok: boolean }>(`/auth/tokens/${id}`, { method: 'DELETE' }),
  getOAuthAuthorizationInfo: (clientId: string, redirectUri: string, scope: string) =>
    request<{ client_name: string; requested_scopes: string[] }>(`/oauth/authorize-info?${new URLSearchParams({ client_id: clientId, redirect_uri: redirectUri, scope })}`),
  completeOAuthAuthorization: (body: { client_id: string; redirect_uri: string; code_challenge: string; code_challenge_method: string; scope: string; resource: string; approved_scopes: string[]; project_ids: number[] }) =>
    request<{ code: string }>('/oauth/authorize/complete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  listMcpOAuthConnections: () => request<McpOAuthConnection[]>('/oauth/connections'),
  revokeMcpOAuthConnection: (id: number) => request<{ ok: boolean }>(`/oauth/connections/${id}`, { method: 'DELETE' }),

  // users (admin)
  listUsers: () => request<User[]>('/users'),
  createUser: (username: string, password: string, role: string, email?: string) =>
    request<User>('/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, role, email: email || '' }),
    }),
  setUserEmail: (id: number, email: string) =>
    request<User>(`/users/${id}/email`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    }),
  deleteUser: (id: number) => request(`/users/${id}`, { method: 'DELETE' }),
  adminEnableTotp: (id: number) => request<{ secret: string; uri: string }>(`/users/${id}/totp`, { method: 'POST' }),
  adminDisableTotp: (id: number) => request(`/users/${id}/totp`, { method: 'DELETE' }),
  updateUserRole: (id: number, role: string) =>
    request<User>(`/users/${id}/role`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    }),
  resetPassword: (id: number, new_password: string) =>
    request(`/users/${id}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password }),
    }),

  // projects
  listProjects: () => request<Project[]>('/projects'),
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  updateAnnotationInstructions: (id: number, annotation_instructions: string) =>
    request<{ annotation_instructions: string }>(`/projects/${id}/annotation-instructions`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ annotation_instructions }),
    }),
  createProject: (name: string, file: File) => {
    const fd = new FormData(); fd.append('name', name); fd.append('file', file)
    return request<Project>('/projects', { method: 'POST', body: fd })
  },
  deleteProject: (id: number) => request(`/projects/${id}`, { method: 'DELETE' }),
  listRows: (projectId: number, params: Record<string, string | number | boolean>) => {
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    return request<RowsResponse>(`/projects/${projectId}/rows?${qs}`)
  },
  getRow: (projectId: number, rowId: number) =>
    request<RowDetail>(`/projects/${projectId}/rows/${rowId}`),
  getAdjacent: (projectId: number, rowId: number, params: Record<string, string | boolean>) => {
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    return request<Adjacent>(`/projects/${projectId}/rows/${rowId}/adjacent?${qs}`)
  },
  updateRow: (projectId: number, rowId: number, body: RowUpdate) =>
    request<RowDetail>(`/projects/${projectId}/rows/${rowId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  batchUpdateRows: (projectId: number, body: {
    ids?: number[]; select_all?: boolean; status: string
    status_filter?: string; relevance_filter?: string; q_filter?: string; disagreement_filter?: string
  }) =>
    request<{ updated: number }>(`/projects/${projectId}/rows/batch`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  getAuditLog: (projectId: number, rowId: number) =>
    request<AuditEntry[]>(`/projects/${projectId}/rows/${rowId}/audit`),
  heartbeat: (projectId: number, rowId: number) =>
    request<{ ok: boolean }>(`/projects/${projectId}/rows/${rowId}/presence`, { method: 'POST' }),
  removePresence: (projectId: number, rowId: number) =>
    request<{ ok: boolean }>(`/projects/${projectId}/rows/${rowId}/presence`, { method: 'DELETE' }),
  getPresence: (projectId: number) =>
    request<PresenceEntry[]>(`/projects/${projectId}/presence`),
  exportProject: async (projectId: number, filename: string) => {
    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`${BASE}/projects/${projectId}/export`, { headers })
    if (!res.ok) throw new Error('匯出失敗')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },

  // llm config (legacy single-slot)
  previewPrompt: (projectId: number) =>
    request<{ example_count: number; prompt: string }>(`/projects/${projectId}/llm-preview`),
  getLLMConfig: (projectId: number) =>
    request<LegacyLLMConfig>(`/projects/${projectId}/llm-config`),
  updateLLMConfig: (projectId: number, config: Omit<LegacyLLMConfig, 'has_api_key'>) =>
    request<LegacyLLMConfig>(`/projects/${projectId}/llm-config`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }),
  listLLMModels: (projectId: number) =>
    request<string[]>(`/projects/${projectId}/llm-models`),

  // llm config multi-slot
  getLLMConfigs: (projectId: number) =>
    request<LLMSlotConfig[]>(`/projects/${projectId}/llm-configs`),
  setLLMConfig: (projectId: number, slot: number, config: Omit<LLMSlotConfig, 'slot'>) =>
    request<LLMSlotConfig>(`/projects/${projectId}/llm-configs/${slot}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    }),
  deleteLLMConfigSlot: (projectId: number, slot: number) =>
    request(`/projects/${projectId}/llm-configs/${slot}`, { method: 'DELETE' }),
  listLLMModelsForSlot: (projectId: number, slot: number) =>
    request<string[]>(`/projects/${projectId}/llm-configs/${slot}/models`),
  previewPromptForSlot: (projectId: number, slot: number) =>
    request<{ example_count: number; prompt: string }>(`/projects/${projectId}/llm-configs/${slot}/preview`),

  // tasks
  listTasks: (projectId: number) =>
    request<Task[]>(`/projects/${projectId}/tasks`),
  createTask: (projectId: number, body: {
    target: 'pending' | 'all' | 'parse_failed'; slot: number; execution_mode: 'api' | 'mcp'; executor_name?: string
  }) =>
    request<Task>(`/projects/${projectId}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  getTask: (projectId: number, taskId: number) =>
    request<Task>(`/projects/${projectId}/tasks/${taskId}`),
  cancelTask: (projectId: number, taskId: number) =>
    request<Task>(`/projects/${projectId}/tasks/${taskId}/cancel`, { method: 'POST' }),
  deleteTask: (projectId: number, taskId: number) =>
    request<{ ok: boolean }>(`/projects/${projectId}/tasks/${taskId}`, { method: 'DELETE' }),

  adoptSlot: (projectId: number, slot: number, target: 'pending' | 'all') =>
    request<{ updated: number }>(`/projects/${projectId}/adopt-slot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot, target }),
    }),
}