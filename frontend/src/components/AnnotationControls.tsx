import { useMemo, useState } from 'react'
import type { LLMResult, RowDetail } from '../api/client'
import {
  AnnotationResult,
  AnnotationSchema,
  GenericLLMResultFields,
  GenericRowFields,
  LabelDefinition,
  coerceAnnotationResult,
} from '../api/annotation'
import { Badge } from '@/components/ui/badge'

function parseList(value: string | null | undefined): string[] {
  if (!value) return []
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return value.split(',').map(item => item.trim()).filter(Boolean)
  }
}

function labelMaps(schema: AnnotationSchema) {
  return {
    byId: new Map(schema.labels.map(label => [label.id, label])),
    byName: new Map(schema.labels.map(label => [label.name, label.id])),
  }
}

function resolveLabel(schema: AnnotationSchema, value: string): string {
  const { byId, byName } = labelMaps(schema)
  return byId.has(value) ? value : byName.get(value) || value
}

function resolveRelevance(schema: AnnotationSchema, value: string | null | undefined): string | null {
  if (!schema.relevance?.enabled || !value) return null
  const byId = new Map(schema.relevance.values.map(item => [item.id, item.id]))
  const byName = new Map(schema.relevance.values.map(item => [item.name, item.id]))
  return byId.get(value) || byName.get(value) || value
}

function addAncestors(schema: AnnotationSchema, selected: string[]): string[] {
  if (!schema.constraints.child_requires_parent) return Array.from(new Set(selected))
  const byId = new Map(schema.labels.map(label => [label.id, label]))
  const result: string[] = []
  const seen = new Set<string>()

  const add = (id: string) => {
    const label = byId.get(id)
    if (label?.parent_id) add(label.parent_id)
    if (!seen.has(id)) {
      seen.add(id)
      result.push(id)
    }
  }
  selected.forEach(add)
  return result
}

export function resultFromRow(row: RowDetail & GenericRowFields, schema: AnnotationSchema): AnnotationResult {
  const canonical = coerceAnnotationResult(row.corrected_result) || coerceAnnotationResult(row.prediction)
  if (canonical) {
    return {
      ...canonical,
      labels: addAncestors(schema, canonical.labels.map(id => resolveLabel(schema, id))),
      relevance: resolveRelevance(schema, canonical.relevance),
    }
  }

  const labels = [
    ...parseList(row.corrected_labels || row.ai_labels),
    ...parseList(row.corrected_emotional_subtypes || row.ai_emotional_subtypes),
  ].map(value => resolveLabel(schema, value))

  return {
    relevance: resolveRelevance(schema, row.corrected_relevance || row.ai_relevance),
    labels: addAncestors(schema, labels),
    reason: row.ai_reason || '',
    metadata: {},
  }
}

export function resultFromLLM(result: LLMResult & GenericLLMResultFields, schema: AnnotationSchema): AnnotationResult {
  const canonical = coerceAnnotationResult(result.result)
  if (canonical) {
    return {
      ...canonical,
      labels: addAncestors(schema, canonical.labels.map(id => resolveLabel(schema, id))),
      relevance: resolveRelevance(schema, canonical.relevance),
    }
  }

  return {
    relevance: resolveRelevance(schema, result.relevance),
    labels: addAncestors(schema, [
      ...parseList(result.labels),
      ...parseList(result.subtypes),
    ].map(value => resolveLabel(schema, value))),
    reason: result.reason || '',
    metadata: {},
  }
}

function descendantsOf(schema: AnnotationSchema, parentId: string): Set<string> {
  const childrenByParent = new Map<string, string[]>()
  schema.labels.forEach(label => {
    if (!label.parent_id) return
    const children = childrenByParent.get(label.parent_id) || []
    children.push(label.id)
    childrenByParent.set(label.parent_id, children)
  })
  const result = new Set<string>()
  const visit = (id: string) => {
    for (const child of childrenByParent.get(id) || []) {
      if (result.has(child)) continue
      result.add(child)
      visit(child)
    }
  }
  visit(parentId)
  return result
}

export function toggleSchemaLabel(schema: AnnotationSchema, current: string[], labelId: string): string[] {
  if (schema.mode === 'single_label') {
    return current.includes(labelId) ? [] : [labelId]
  }

  if (current.includes(labelId)) {
    const descendants = schema.constraints.child_requires_parent ? descendantsOf(schema, labelId) : new Set<string>()
    return current.filter(id => id !== labelId && !descendants.has(id))
  }
  return addAncestors(schema, [...current, labelId])
}

export function validateAnnotationSelection(
  schema: AnnotationSchema,
  result: AnnotationResult,
): string[] {
  const issues: string[] = []
  const byId = new Map(schema.labels.map(label => [label.id, label]))
  const selected = new Set(result.labels)

  if (schema.relevance?.enabled) {
    const allowed = new Set(schema.relevance.values.map(item => item.id))
    if (!result.relevance) issues.push('請選擇相關性')
    else if (!allowed.has(result.relevance)) issues.push(`相關性 ${result.relevance} 不在目前 schema 中`)
  }

  const unknown = result.labels.filter(id => !byId.has(id))
  if (unknown.length > 0) issues.push(`含未知標籤：${Array.from(new Set(unknown)).join(', ')}`)

  const disabled = result.labels.filter(id => byId.get(id)?.enabled === false)
  if (disabled.length > 0) issues.push(`含已停用標籤：${disabled.join(', ')}`)

  if (schema.mode === 'single_label' && result.labels.length > 1) {
    issues.push('此專案為單選分類，只能選擇一個標籤')
  }
  if (schema.constraints.max_labels !== null && result.labels.length > schema.constraints.max_labels) {
    issues.push(`最多只能選擇 ${schema.constraints.max_labels} 個標籤`)
  }

  if (schema.constraints.child_requires_parent) {
    result.labels.forEach(id => {
      const parentId = byId.get(id)?.parent_id
      if (parentId && !selected.has(parentId)) issues.push(`${byId.get(id)?.name || id} 必須同時選擇父標籤`)
    })
  }

  schema.constraints.require_child_for.forEach(parentId => {
    if (!selected.has(parentId)) return
    const hasChild = schema.labels.some(label => label.parent_id === parentId && selected.has(label.id))
    if (!hasChild) issues.push(`${byId.get(parentId)?.name || parentId} 至少需要選擇一個子標籤`)
  })
  return Array.from(new Set(issues))
}

export function labelDisplayName(schema: AnnotationSchema, labelId: string): string {
  return schema.labels.find(label => label.id === labelId)?.name || labelId
}

export function labelPath(schema: AnnotationSchema, labelId: string): string {
  const byId = new Map(schema.labels.map(label => [label.id, label]))
  const names: string[] = []
  let current: LabelDefinition | undefined = byId.get(labelId)
  const seen = new Set<string>()
  while (current && !seen.has(current.id)) {
    seen.add(current.id)
    names.unshift(current.name)
    current = current.parent_id ? byId.get(current.parent_id) : undefined
  }
  return names.join(' / ') || labelId
}

export function relevanceDisplayName(schema: AnnotationSchema, relevance: string | null): string {
  if (!relevance) return '—'
  return schema.relevance?.values.find(item => item.id === relevance)?.name || relevance
}

function LabelTree({
  schema,
  parentId,
  selected,
  onToggle,
  depth = 0,
}: {
  schema: AnnotationSchema
  parentId: string | null
  selected: string[]
  onToggle: (id: string) => void
  depth?: number
}) {
  const children = schema.labels.filter(label => label.parent_id === parentId)
  if (children.length === 0) return null

  return (
    <div className={depth > 0 ? 'ml-4 pl-3 border-l border-border space-y-2' : 'space-y-3'}>
      {children.map(label => {
        const active = selected.includes(label.id)
        const requireChild = schema.constraints.require_child_for.includes(label.id)
        return (
          <div key={label.id} className="space-y-2">
            <div className="flex items-start gap-2">
              <button
                type="button"
                disabled={!label.enabled}
                onClick={() => onToggle(label.id)}
                title={label.description || label.name}
                className={`text-xs px-3 py-1.5 rounded-full border transition-all duration-150 ${
                  active
                    ? 'bg-primary text-primary-foreground border-primary shadow-sm'
                    : label.enabled
                      ? 'bg-card text-muted-foreground border-border hover:border-primary/50 hover:text-primary'
                      : 'bg-muted text-muted-foreground/40 border-border cursor-not-allowed'
                }`}
              >
                {label.name}
              </button>
              <div className="min-w-0 pt-0.5">
                {requireChild && <Badge variant="outline" className="text-[10px] mr-1">需選子項</Badge>}
                {!label.enabled && <Badge variant="outline" className="text-[10px]">已停用</Badge>}
                {label.description && (
                  <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">{label.description}</p>
                )}
              </div>
            </div>
            <LabelTree
              schema={schema}
              parentId={label.id}
              selected={selected}
              onToggle={onToggle}
              depth={depth + 1}
            />
          </div>
        )
      })}
    </div>
  )
}

export function AnnotationFields({
  schema,
  result,
  onChange,
}: {
  schema: AnnotationSchema
  result: AnnotationResult
  onChange: (result: AnnotationResult) => void
}) {
  const issues = useMemo(() => validateAnnotationSelection(schema, result), [schema, result])
  const onToggle = (labelId: string) => {
    onChange({ ...result, labels: toggleSchemaLabel(schema, result.labels, labelId) })
  }

  return (
    <div className="space-y-5">
      {schema.relevance?.enabled && (
        <div>
          <p className="text-sm font-medium text-foreground mb-2">相關性</p>
          <div className="flex flex-wrap gap-4">
            {schema.relevance.values.map(value => (
              <label key={value.id} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="relevance"
                  value={value.id}
                  checked={result.relevance === value.id}
                  onChange={() => onChange({ ...result, relevance: value.id })}
                  className="text-primary"
                />
                <span className={`text-sm ${result.relevance === value.id ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
                  {value.name}
                </span>
              </label>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <p className="text-sm font-medium text-foreground">分類標籤</p>
          <Badge variant="outline" className="text-[10px]">
            {schema.mode === 'single_label' ? '單選' : '複選'}
          </Badge>
          {schema.constraints.max_labels !== null && (
            <span className="text-xs text-muted-foreground">最多 {schema.constraints.max_labels} 個</span>
          )}
        </div>
        <LabelTree schema={schema} parentId={null} selected={result.labels} onToggle={onToggle} />
        {schema.labels.length === 0 && (
          <p className="text-xs text-muted-foreground">此專案尚未設定任何標籤。</p>
        )}
      </div>

      {issues.length > 0 && (
        <div className="rounded-lg border border-amber-200 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-700 dark:text-amber-300 space-y-1">
          {issues.map(issue => <div key={issue}>• {issue}</div>)}
        </div>
      )}
    </div>
  )
}

export function LLMComparison({
  results,
  schema,
  onAdopt,
}: {
  results: LLMResult[]
  schema: AnnotationSchema
  onAdopt: (result: AnnotationResult) => void
}) {
  const [adoptedSlot, setAdoptedSlot] = useState<number | null>(null)
  const canonical = useMemo(
    () => results.map(result => ({ raw: result, result: resultFromLLM(result, schema) })),
    [results, schema],
  )
  if (canonical.length === 0) return null

  const allLabels = Array.from(new Set(canonical.flatMap(item => item.result.labels)))
  const relevanceValues = canonical.map(item => item.result.relevance).filter(Boolean)
  const relevanceDisagreement = new Set(relevanceValues).size > 1
  const isLabelDisputed = (label: string) => {
    const count = canonical.filter(item => item.result.labels.includes(label)).length
    return count > 0 && count < canonical.length
  }
  const hasDisagreement = relevanceDisagreement || allLabels.some(isLabelDisputed)

  const handleAdopt = (slot: number, result: AnnotationResult) => {
    onAdopt(result)
    setAdoptedSlot(slot)
    window.setTimeout(() => setAdoptedSlot(null), 1200)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">LLM 分析比對</span>
        {hasDisagreement && <Badge variant="outline" className="text-xs border-amber-300 text-amber-600 dark:text-amber-400">有歧異</Badge>}
      </div>
      <div className="space-y-2">
        {canonical.map(({ raw, result }) => {
          const isWarning = !!result.reason?.startsWith('⚠️') || !!raw.reason?.startsWith('⚠️')
          const rowHasDisagreement = relevanceDisagreement || result.labels.some(isLabelDisputed)
            || allLabels.some(label => isLabelDisputed(label) && !result.labels.includes(label))
          return (
            <div key={raw.slot} className={`rounded-lg px-3 py-2.5 text-xs space-y-1.5 ${
              isWarning ? 'bg-red-50 dark:bg-red-900/20 ring-1 ring-red-200 dark:ring-red-800/40'
                : rowHasDisagreement ? 'bg-amber-50 dark:bg-amber-900/20 ring-1 ring-amber-200 dark:ring-amber-800/40'
                : 'bg-muted/50'
            }`}>
              <div className="flex items-start gap-3">
                <span className="shrink-0 truncate font-medium text-muted-foreground min-w-12 max-w-32"
                  title={`結果槽 ${raw.slot}：${raw.name || `LLM ${raw.slot}`}`}>
                  {raw.name || `LLM ${raw.slot}`}
                </span>
                <span className="shrink-0 font-semibold min-w-10 text-foreground">
                  {relevanceDisplayName(schema, result.relevance)}
                </span>
                <span className="flex flex-wrap gap-1 flex-1">
                  {result.labels.length === 0
                    ? <span className="text-muted-foreground/50">(無標籤)</span>
                    : result.labels.map(label => (
                      <span key={label} className={`px-1.5 py-0.5 rounded ${
                        isLabelDisputed(label)
                          ? 'bg-amber-200 dark:bg-amber-800 text-amber-800 dark:text-amber-200'
                          : 'bg-primary/10 text-primary'
                      }`} title={labelPath(schema, label)}>
                        {labelDisplayName(schema, label)}
                      </span>
                    ))}
                </span>
                <button
                  type="button"
                  onClick={() => handleAdopt(raw.slot, result)}
                  className={`shrink-0 px-2.5 py-1 text-xs rounded-md border font-medium whitespace-nowrap transition-all duration-200 ${
                    adoptedSlot === raw.slot
                      ? 'bg-emerald-500 border-emerald-500 text-white scale-95'
                      : 'border-primary/30 text-primary hover:bg-primary/5'
                  }`}
                >
                  {adoptedSlot === raw.slot ? '✓ 已採用' : '採用'}
                </button>
              </div>
              {result.reason && (
                <div className={`pl-[88px] leading-relaxed ${isWarning ? 'text-red-600 dark:text-red-400 font-medium' : 'text-muted-foreground'}`}>
                  {result.reason}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
