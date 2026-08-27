import { useEffect, useMemo, useRef, useState } from 'react'
import type { AnnotationSchema, LabelDefinition } from '../api/annotation'
import {
  createGenericProject,
  previewImport,
  type ImportPreview,
  type InputMapping,
} from '../api/imports'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

const EMPTY_MAPPING: InputMapping = {
  text_field: '',
  id_field: null,
  labels: null,
  hierarchy: null,
  metadata_fields: [],
  context_fields: [],
}

function makeLabel(index: number, parentId: string | null = null): LabelDefinition {
  return {
    id: `label_${index}`,
    name: `標籤 ${index}`,
    description: '',
    parent_id: parentId,
    examples: [],
    enabled: true,
  }
}

function autoId(name: string, fallback: string): string {
  const value = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!value) return fallback
  if (/^[a-z0-9_]+$/.test(value)) return value
  return fallback
}

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter(item => item !== value) : [...values, value]
}

export default function ImportWizardDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (projectId: number) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<InputMapping>(EMPTY_MAPPING)
  const [labels, setLabels] = useState<LabelDefinition[]>([makeLabel(1)])
  const [mode, setMode] = useState<'single_label' | 'multi_label'>('multi_label')
  const [maxLabels, setMaxLabels] = useState('')
  const [childRequiresParent, setChildRequiresParent] = useState(true)
  const [requireChildFor, setRequireChildFor] = useState<string[]>([])
  const [relevanceEnabled, setRelevanceEnabled] = useState(true)
  const [relevantName, setRelevantName] = useState('相關')
  const [irrelevantName, setIrrelevantName] = useState('無關')
  const [instructions, setInstructions] = useState('')
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setStep(1)
    setName('')
    setFile(null)
    setPreview(null)
    setMapping(EMPTY_MAPPING)
    setLabels([makeLabel(1)])
    setMode('multi_label')
    setMaxLabels('')
    setChildRequiresParent(true)
    setRequireChildFor([])
    setRelevanceEnabled(true)
    setRelevantName('相關')
    setIrrelevantName('無關')
    setInstructions('')
    setWorking(false)
    setError(null)
  }

  useEffect(() => {
    if (!open) reset()
  }, [open])

  const columns = preview?.columns ?? []
  const parentsWithChildren = useMemo(
    () => labels.filter(label => labels.some(child => child.parent_id === label.id)),
    [labels],
  )

  const schema: AnnotationSchema = useMemo(() => ({
    version: 1,
    mode,
    labels,
    constraints: {
      max_depth: 4,
      max_labels: maxLabels.trim() ? Math.max(1, Number(maxLabels)) : null,
      child_requires_parent: childRequiresParent,
      require_child_for: requireChildFor.filter(id => labels.some(label => label.id === id)),
    },
    relevance: relevanceEnabled
      ? {
          enabled: true,
          values: [
            { id: 'relevant', name: relevantName || '相關' },
            { id: 'irrelevant', name: irrelevantName || '無關' },
          ],
        }
      : null,
  }), [
    mode,
    labels,
    maxLabels,
    childRequiresParent,
    requireChildFor,
    relevanceEnabled,
    relevantName,
    irrelevantName,
  ])

  const handlePreview = async () => {
    if (!name.trim() || !file) return
    setWorking(true)
    setError(null)
    try {
      const result = await previewImport(file)
      setPreview(result)
      setMapping(result.inferred_mapping)
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : '無法預覽檔案')
    } finally {
      setWorking(false)
    }
  }

  const addLabel = (parentId: string | null = null) => {
    const nextIndex = labels.length + 1
    setLabels(current => [...current, makeLabel(nextIndex, parentId)])
  }

  const updateLabel = (index: number, patch: Partial<LabelDefinition>) => {
    setLabels(current => current.map((item, i) => i === index ? { ...item, ...patch } : item))
  }

  const updateLabelName = (index: number, value: string) => {
    setLabels(current => current.map((item, i) => {
      if (i !== index) return item
      const fallback = item.id.startsWith('label_') ? `label_${index + 1}` : item.id
      return { ...item, name: value, id: item.id.startsWith('label_') ? autoId(value, fallback) : item.id }
    }))
  }

  const removeLabel = (index: number) => {
    const id = labels[index]?.id
    setLabels(current => current
      .filter((_, i) => i !== index)
      .map(label => label.parent_id === id ? { ...label, parent_id: null } : label))
    if (id) setRequireChildFor(current => current.filter(value => value !== id))
  }

  const validateMapping = (): string | null => {
    if (!mapping.text_field) return '請指定主要文字欄位'
    if (!columns.includes(mapping.text_field)) return '主要文字欄位不存在於檔案中'
    return null
  }

  const validateSchema = (): string | null => {
    if (labels.length === 0) return '至少需要一個標籤'
    const ids = labels.map(label => label.id.trim())
    const names = labels.map(label => label.name.trim())
    if (ids.some(id => !id)) return '每個標籤都需要 ID'
    if (names.some(value => !value)) return '每個標籤都需要名稱'
    if (new Set(ids).size !== ids.length) return '標籤 ID 不可重複'
    if (mode === 'single_label' && labels.some(label => label.parent_id)) return '單選模式目前不支援階層標籤，請改成多選或移除 parent'
    if (maxLabels.trim() && (!Number.isFinite(Number(maxLabels)) || Number(maxLabels) < 1)) return '最多標籤數必須大於 0'
    return null
  }

  const goToSchema = () => {
    const issue = validateMapping()
    if (issue) { setError(issue); return }
    setError(null)
    setStep(3)
  }

  const goToConfirm = () => {
    const issue = validateSchema()
    if (issue) { setError(issue); return }
    setError(null)
    setStep(4)
  }

  const handleCreate = async () => {
    if (!file) return
    const mappingIssue = validateMapping()
    const schemaIssue = validateSchema()
    if (mappingIssue || schemaIssue) {
      setError(mappingIssue || schemaIssue)
      return
    }
    setWorking(true)
    setError(null)
    try {
      const project = await createGenericProject({
        name: name.trim(),
        file,
        mapping,
        schema,
        annotationInstructions: instructions,
      })
      onOpenChange(false)
      onCreated(project.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : '建立專案失敗')
    } finally {
      setWorking(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>新增標注專案</DialogTitle>
          <div className="flex gap-2 pt-2 text-xs text-muted-foreground">
            {['上傳資料', '欄位 Mapping', '標籤與規則', '確認建立'].map((label, index) => (
              <span key={label} className={step === index + 1 ? 'font-semibold text-primary' : ''}>
                {index + 1}. {label}{index < 3 ? ' →' : ''}
              </span>
            ))}
          </div>
        </DialogHeader>

        {step === 1 && (
          <div className="space-y-5 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="generic-project-name">專案名稱</Label>
              <Input id="generic-project-name" value={name} onChange={event => setName(event.target.value)} placeholder="例：客服問題分類" autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label>資料檔案</Label>
              <div onClick={() => fileRef.current?.click()}
                className="border-2 border-dashed border-input rounded-xl p-8 text-center cursor-pointer hover:border-primary/50 transition-colors">
                {file
                  ? <div><p className="text-sm text-primary font-medium">{file.name}</p><p className="text-xs text-muted-foreground mt-1">點擊可更換檔案</p></div>
                  : <div><p className="text-sm text-muted-foreground">點擊選擇檔案</p><p className="text-xs text-muted-foreground/60 mt-1">CSV / XLSX / XLS / JSON / JSONL</p></div>}
              </div>
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls,.json,.jsonl" className="hidden"
                onChange={event => { setFile(event.target.files?.[0] || null); setPreview(null) }} />
            </div>
          </div>
        )}

        {step === 2 && preview && (
          <div className="space-y-6 py-2">
            <div className="rounded-xl border border-border overflow-hidden">
              <div className="px-4 py-2.5 bg-muted/40 text-xs text-muted-foreground">{preview.filename} · {preview.row_count} 筆 · {preview.columns.length} 欄</div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs">
                  <thead><tr className="border-b border-border">{preview.columns.map(column => <th key={column} className="text-left px-3 py-2 whitespace-nowrap font-medium">{column}</th>)}</tr></thead>
                  <tbody>{preview.rows.slice(0, 5).map((row, rowIndex) => (
                    <tr key={rowIndex} className="border-b border-border last:border-0">
                      {preview.columns.map(column => <td key={column} className="px-3 py-2 max-w-52 truncate text-muted-foreground">{String(row[column] ?? '')}</td>)}
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </div>

            <div className="grid md:grid-cols-2 gap-5">
              <div className="space-y-1.5">
                <Label>主要標註文字 *</Label>
                <select value={mapping.text_field} onChange={event => setMapping(current => ({ ...current, text_field: event.target.value }))}
                  className="w-full h-9 rounded-md border border-input bg-card px-3 text-sm">
                  <option value="">請選擇</option>{columns.map(column => <option key={column} value={column}>{column}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>資料 ID</Label>
                <select value={mapping.id_field || ''} onChange={event => setMapping(current => ({ ...current, id_field: event.target.value || null }))}
                  className="w-full h-9 rounded-md border border-input bg-card px-3 text-sm">
                  <option value="">不指定</option>{columns.map(column => <option key={column} value={column}>{column}</option>)}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label>原始標籤欄位（可選）</Label>
                <select value={mapping.labels?.field || ''} onChange={event => setMapping(current => ({
                  ...current,
                  labels: event.target.value ? { field: event.target.value, format: 'single', delimiter: null } : null,
                }))} className="w-full h-9 rounded-md border border-input bg-card px-3 text-sm">
                  <option value="">沒有既有標籤</option>{columns.map(column => <option key={column} value={column}>{column}</option>)}
                </select>
              </div>
              {mapping.labels && (
                <div className="space-y-1.5">
                  <Label>原始標籤格式</Label>
                  <div className="flex gap-2">
                    <select value={mapping.labels.format} onChange={event => setMapping(current => ({
                      ...current,
                      labels: current.labels ? { ...current.labels, format: event.target.value as 'single' | 'delimiter' | 'json' } : null,
                    }))} className="h-9 flex-1 rounded-md border border-input bg-card px-3 text-sm">
                      <option value="single">單一值</option><option value="delimiter">分隔字串</option><option value="json">JSON array</option>
                    </select>
                    {mapping.labels.format === 'delimiter' && <Input className="w-28" value={mapping.labels.delimiter || ','} onChange={event => setMapping(current => ({ ...current, labels: current.labels ? { ...current.labels, delimiter: event.target.value } : null }))} placeholder="," />}
                  </div>
                </div>
              )}
            </div>

            <div className="grid md:grid-cols-2 gap-5">
              <div>
                <p className="text-sm font-medium mb-2">Context 欄位</p>
                <div className="flex flex-wrap gap-2">{columns.filter(column => column !== mapping.text_field).map(column => (
                  <label key={column} className="flex items-center gap-2 border border-border rounded-lg px-2.5 py-1.5 text-xs cursor-pointer">
                    <input type="checkbox" checked={mapping.context_fields.includes(column)} onChange={() => setMapping(current => ({ ...current, context_fields: toggleValue(current.context_fields, column) }))} /> {column}
                  </label>
                ))}</div>
              </div>
              <div>
                <p className="text-sm font-medium mb-2">Metadata 欄位</p>
                <div className="flex flex-wrap gap-2">{columns.filter(column => column !== mapping.text_field).map(column => (
                  <label key={column} className="flex items-center gap-2 border border-border rounded-lg px-2.5 py-1.5 text-xs cursor-pointer">
                    <input type="checkbox" checked={mapping.metadata_fields.includes(column)} onChange={() => setMapping(current => ({ ...current, metadata_fields: toggleValue(current.metadata_fields, column) }))} /> {column}
                  </label>
                ))}</div>
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6 py-2">
            <div className="grid md:grid-cols-3 gap-4">
              <div className="space-y-1.5"><Label>分類模式</Label><select value={mode} onChange={event => setMode(event.target.value as 'single_label' | 'multi_label')} className="w-full h-9 rounded-md border border-input bg-card px-3 text-sm"><option value="multi_label">多選</option><option value="single_label">單選</option></select></div>
              <div className="space-y-1.5"><Label>最多標籤數</Label><Input type="number" min={1} value={maxLabels} onChange={event => setMaxLabels(event.target.value)} placeholder="不限" /></div>
              <div className="space-y-2 pt-6"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={childRequiresParent} onChange={event => setChildRequiresParent(event.target.checked)} /> 子標籤必須包含父標籤</label></div>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between"><div><p className="text-sm font-medium">標籤 Schema</p><p className="text-xs text-muted-foreground">可用 Parent 建立任意階層。</p></div><Button variant="outline" size="sm" onClick={() => addLabel(null)}>+ 標籤</Button></div>
              <div className="space-y-2">{labels.map((label, index) => (
                <div key={`${label.id}-${index}`} className="grid grid-cols-12 gap-2 items-center border border-border rounded-xl p-3">
                  <Input className="col-span-3" value={label.name} onChange={event => updateLabelName(index, event.target.value)} placeholder="顯示名稱" />
                  <Input className="col-span-3 font-mono text-xs" value={label.id} onChange={event => updateLabel(index, { id: event.target.value.trim() })} placeholder="label_id" />
                  <select className="col-span-3 h-9 rounded-md border border-input bg-card px-2 text-xs" value={label.parent_id || ''} onChange={event => updateLabel(index, { parent_id: event.target.value || null })} disabled={mode === 'single_label'}>
                    <option value="">頂層</option>{labels.filter((_, i) => i !== index).map(parent => <option key={parent.id} value={parent.id}>{parent.name}</option>)}
                  </select>
                  <Input className="col-span-2" value={label.description} onChange={event => updateLabel(index, { description: event.target.value })} placeholder="說明" />
                  <Button className="col-span-1" variant="ghost" size="sm" onClick={() => removeLabel(index)} disabled={labels.length <= 1}>×</Button>
                </div>
              ))}</div>
            </div>

            {parentsWithChildren.length > 0 && (
              <div><p className="text-sm font-medium mb-2">選到父標籤時，是否強制至少選一個直接子標籤</p><div className="flex flex-wrap gap-2">{parentsWithChildren.map(parent => <label key={parent.id} className="flex items-center gap-2 border border-border rounded-lg px-3 py-2 text-xs"><input type="checkbox" checked={requireChildFor.includes(parent.id)} onChange={() => setRequireChildFor(current => toggleValue(current, parent.id))} />{parent.name}</label>)}</div></div>
            )}

            <div className="grid md:grid-cols-3 gap-4 items-end">
              <label className="flex items-center gap-2 text-sm pb-2"><input type="checkbox" checked={relevanceEnabled} onChange={event => setRelevanceEnabled(event.target.checked)} /> 啟用相關性</label>
              {relevanceEnabled && <><div className="space-y-1.5"><Label>Relevant 顯示名稱</Label><Input value={relevantName} onChange={event => setRelevantName(event.target.value)} /></div><div className="space-y-1.5"><Label>Irrelevant 顯示名稱</Label><Input value={irrelevantName} onChange={event => setIrrelevantName(event.target.value)} /></div></>}
            </div>

            <div className="space-y-1.5"><Label>標註規則 / Instructions</Label><textarea value={instructions} onChange={event => setInstructions(event.target.value)} rows={4} placeholder="例：依照使用者主要希望客服處理的問題分類；若同時涉及配送與退款可複選。" className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm resize-y" /></div>
          </div>
        )}

        {step === 4 && preview && (
          <div className="space-y-5 py-3">
            <div className="grid md:grid-cols-2 gap-4">
              <div className="rounded-xl border border-border p-4 space-y-2 text-sm"><p className="font-medium">資料 Mapping</p><p><span className="text-muted-foreground">主要文字：</span>{mapping.text_field}</p><p><span className="text-muted-foreground">ID：</span>{mapping.id_field || '不指定'}</p><p><span className="text-muted-foreground">Context：</span>{mapping.context_fields.join(', ') || '無'}</p><p><span className="text-muted-foreground">Metadata：</span>{mapping.metadata_fields.join(', ') || '無'}</p></div>
              <div className="rounded-xl border border-border p-4 space-y-2 text-sm"><p className="font-medium">標籤規則</p><p>{mode === 'multi_label' ? '多選' : '單選'} · {labels.length} 個標籤</p><p><span className="text-muted-foreground">最多：</span>{maxLabels || '不限'}</p><p><span className="text-muted-foreground">相關性：</span>{relevanceEnabled ? `${relevantName} / ${irrelevantName}` : '停用'}</p></div>
            </div>
            <div className="rounded-xl border border-border p-4"><p className="text-sm font-medium mb-3">Schema 預覽</p><div className="space-y-1 text-sm">{labels.map(label => <div key={label.id} style={{ paddingLeft: `${labels.some(parent => parent.id === label.parent_id) ? 20 : 0}px` }}><span className="font-medium">{label.name}</span><span className="text-xs text-muted-foreground ml-2 font-mono">{label.id}</span></div>)}</div></div>
            <div className="rounded-xl bg-muted/40 p-4 text-sm"><span className="font-medium">建立後：</span>系統會保存完整 `original_data`，並把 <span className="font-mono">{mapping.text_field}</span> 寫入 canonical `rows.text`；不會改寫來源檔資料。</div>
          </div>
        )}

        {error && <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-2.5 text-sm text-destructive">{error}</div>}

        <DialogFooter className="gap-2">
          {step > 1 && <Button variant="outline" onClick={() => { setError(null); setStep(current => current - 1) }} disabled={working}>上一步</Button>}
          {step === 1 && <Button onClick={handlePreview} disabled={!name.trim() || !file || working}>{working ? '讀取中…' : '下一步：預覽資料'}</Button>}
          {step === 2 && <Button onClick={goToSchema}>下一步：標籤與規則</Button>}
          {step === 3 && <Button onClick={goToConfirm}>下一步：確認</Button>}
          {step === 4 && <Button onClick={handleCreate} disabled={working}>{working ? '建立中…' : `建立 ${preview?.row_count || 0} 筆專案`}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
