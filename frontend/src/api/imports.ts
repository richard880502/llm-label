import { clearToken, getToken } from './client'
import type { AnnotationSchema } from './annotation'

const BASE = '/api'

export interface LabelFieldMapping {
  field: string
  format: 'single' | 'delimiter' | 'json'
  delimiter?: string | null
}

export interface HierarchyFieldMapping {
  parent_field?: string | null
  child_field?: string | null
}

export interface InputMapping {
  text_field: string
  id_field?: string | null
  labels?: LabelFieldMapping | null
  hierarchy?: HierarchyFieldMapping | null
  metadata_fields: string[]
  context_fields: string[]
}

export interface ImportPreview {
  filename: string
  row_count: number
  columns: string[]
  rows: Record<string, unknown>[]
  inferred_mapping: InputMapping
}

export interface GenericProjectCreated {
  id: number
  name: string
  filename: string
  total_rows: number
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
    let message = res.statusText
    try {
      const payload = await res.json()
      if (typeof payload?.detail === 'string') message = payload.detail
      else if (payload?.detail?.issues) message = payload.detail.issues.join('；')
      else if (payload?.detail?.message) message = payload.detail.message
      else message = JSON.stringify(payload.detail ?? payload)
    } catch {
      message = await res.text().catch(() => message)
    }
    const err = new Error(message) as Error & { status: number }
    err.status = res.status
    throw err
  }
  return res.json()
}

export function previewImport(file: File): Promise<ImportPreview> {
  const form = new FormData()
  form.append('file', file)
  return request('/imports/preview', { method: 'POST', body: form })
}

export function createGenericProject(input: {
  name: string
  file: File
  mapping: InputMapping
  schema: AnnotationSchema
  annotationInstructions: string
}): Promise<GenericProjectCreated> {
  const form = new FormData()
  form.append('name', input.name)
  form.append('file', input.file)
  form.append('mapping_json', JSON.stringify(input.mapping))
  form.append('schema_json', JSON.stringify(input.schema))
  form.append('annotation_instructions', input.annotationInstructions)
  return request('/imports/projects', { method: 'POST', body: form })
}
