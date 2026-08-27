import { clearToken, getToken } from './client'

const BASE = '/api'

export interface LabelDefinition {
  id: string
  name: string
  description: string
  parent_id: string | null
  examples: string[]
  enabled: boolean
}

export interface RelevanceValue {
  id: string
  name: string
}

export interface RelevanceSchema {
  enabled: boolean
  values: RelevanceValue[]
}

export interface SchemaConstraints {
  max_depth: number
  max_labels: number | null
  child_requires_parent: boolean
  require_child_for: string[]
}

export interface AnnotationSchema {
  version: number
  mode: 'single_label' | 'multi_label'
  labels: LabelDefinition[]
  constraints: SchemaConstraints
  relevance: RelevanceSchema | null
}

export interface AnnotationResult {
  relevance: string | null
  labels: string[]
  reason: string
  metadata?: Record<string, unknown>
}

export interface GenericRowFields {
  text?: string | null
  prediction?: AnnotationResult | string | null
  corrected_result?: AnnotationResult | string | null
}

export interface GenericLLMResultFields {
  result?: AnnotationResult | string | null
}

export interface GenericRowUpdate {
  corrected_result?: AnnotationResult
  reviewer_note?: string
  status?: string
  version?: number
}

function errorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'string') return payload
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const issues = (detail as { issues?: unknown }).issues
      if (Array.isArray(issues)) return issues.map(String).join('；')
      return JSON.stringify(detail)
    }
    return JSON.stringify(payload)
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { ...(init?.headers as Record<string, string> | undefined) }
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, { ...init, headers, cache: 'no-store' })
  if (res.status === 401) {
    clearToken()
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    let payload: unknown = null
    try { payload = await res.json() } catch { payload = await res.text().catch(() => '') }
    const err = new Error(errorMessage(payload, res.statusText)) as Error & { status: number }
    err.status = res.status
    throw err
  }
  return res.json()
}

export function getProjectSchema(projectId: number): Promise<AnnotationSchema> {
  return request<AnnotationSchema>(`/projects/${projectId}/schema`)
}

export function updateGenericRow(
  projectId: number,
  rowId: number,
  body: GenericRowUpdate,
): Promise<unknown> {
  return request(`/projects/${projectId}/rows/${rowId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function coerceAnnotationResult(value: unknown): AnnotationResult | null {
  if (!value) return null
  let payload = value
  if (typeof value === 'string') {
    try { payload = JSON.parse(value) } catch { return null }
  }
  if (!payload || typeof payload !== 'object') return null
  const obj = payload as Partial<AnnotationResult>
  if (!Array.isArray(obj.labels)) return null
  return {
    relevance: typeof obj.relevance === 'string' ? obj.relevance : null,
    labels: obj.labels.filter((item): item is string => typeof item === 'string'),
    reason: typeof obj.reason === 'string' ? obj.reason : '',
    metadata: obj.metadata && typeof obj.metadata === 'object' ? obj.metadata : {},
  }
}
