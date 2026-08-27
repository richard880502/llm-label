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

function SectionHeader({ number, title, description }: { number: number; title: string; description: string }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
        {number}
      </span>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}

function FieldCheckList({
  columns,
  selected,
  onToggle,
}: {
  columns: string[]
  selected: string[]
  onToggle: (column: string) => void
}) {
  if (columns.length === 0) {
    return <p className="text-xs text-muted-foreground">沒有其他可選欄位</p>
  }
  return (
    <div className="flex flex-wrap gap-2">
      {columns.map(column => (
        <label
          key={column}
          className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors ${
            selected.includes(column)
              ? 'border-primary/40 bg-primary/5 text-foreground'
              : 'border-border hover:border-primary/30'
          }`}
        >
          <input type="checkbox" checked={selected.includes(column)} onChange={() => onToggle(column)} />
          {column}
        </label>
      ))}
    </div>
  )
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
  const auxiliaryColumns = columns.filter(column => column !== mapping.text_field)
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

  const handleCreate = async () => {
    if (!file || !preview) return
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
      <DialogContent className="sm:max-w-3xl max-h-[92vh] overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-6 py-5">
          <DialogTitle>新增標注專案</DialogTitle>
          <p className="text-xs leading-5 text-muted-foreground">
            上傳資料後一路往下完成欄位、標籤與規則設定。欄位名稱不限，只需要指定一個主要文字欄位。
          </p>
        </DialogHeader>

        <div className="overflow-y-auto px-6 py-6">
          <div className="mx-auto max-w-2xl space-y-8">
            <section className="space-y-4">
              <SectionHeader
                number={1}
                title="專案與資料"
                description="先命名專案並上傳資料。支援 CSV、XLSX、XLS、JSON 與 JSONL。"
              />
              <div className="space-y-4 pl-10">
                <div className="space-y-1.5">
                  <Label htmlFor="generic-project-name">專案名稱</Label>
                  <Input
                    id="generic-project-name"
                    value={name}
                    onChange={event => setName(event.target.value)}
                    placeholder="例：客服問題分類"
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>資料檔案</Label>
                  <div
                    onClick={() => fileRef.current?.click()}
                    className="cursor-pointer rounded-xl border-2 border-dashed border-input p-8 text-center transition-colors hover:border-primary/50"
                  >
                    {file ? (
                      <div>
                        <p className="text-sm font-medium text-primary">{file.name}</p>
                        <p className="mt-1 text-xs text-muted-foreground">點擊可更換檔案</p>
                      </div>
                    ) : (
                      <div>
                        <p className="text-sm text-muted-foreground">點擊選擇檔案</p>
                        <p className="mt-1 text-xs text-muted-foreground/60">CSV / XLSX / XLS / JSON / JSONL</p>
                      </div>
                    )}
                  </div>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".csv,.xlsx,.xls,.json,.jsonl"
                    className="hidden"
                    onChange={event => {
                      setFile(event.target.files?.[0] || null)
                      setPreview(null)
                      setError(null)
                    }}
                  />
                </div>
                <Button onClick={handlePreview} disabled={!name.trim() || !file || working}>
                  {working && !preview ? '讀取中…' : preview ? '重新讀取資料' : '讀取資料並開始設定'}
                </Button>
              </div>
            </section>

            {preview && (
              <>
                <div className="border-t border-border" />

                <section className="space-y-4">
                  <SectionHeader
                    number={2}
                    title="資料預覽"
                    description="先確認系統讀到的欄位與內容是否正確，再往下指定每個欄位的用途。"
                  />
                  <div className="pl-10">
                    <div className="overflow-hidden rounded-xl border border-border">
                      <div className="bg-muted/40 px-4 py-2.5 text-xs text-muted-foreground">
                        {preview.filename} · {preview.row_count} 筆 · {preview.columns.length} 欄
                      </div>
                      <div className="overflow-x-auto">
                        <table className="min-w-full text-xs">
                          <thead>
                            <tr className="border-b border-border">
                              {preview.columns.map(column => (
                                <th key={column} className="whitespace-nowrap px-3 py-2 text-left font-medium">{column}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {preview.rows.slice(0, 5).map((row, rowIndex) => (
                              <tr key={rowIndex} className="border-b border-border last:border-0">
                                {preview.columns.map(column => (
                                  <td key={column} className="max-w-52 truncate px-3 py-2 text-muted-foreground">
                                    {String(row[column] ?? '')}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </section>

                <div className="border-t border-border" />

                <section className="space-y-4">
                  <SectionHeader
                    number={3}
                    title="欄位 Mapping"
                    description="指定哪個欄位是主要文字、ID，以及資料中是否已經存在標籤。"
                  />
                  <div className="space-y-5 pl-10">
                    <div className="space-y-1.5">
                      <Label>主要標註文字 *</Label>
                      <p className="text-xs text-muted-foreground">LLM 與人工標註主要判斷的文字內容。</p>
                      <select
                        value={mapping.text_field}
                        onChange={event => setMapping(current => ({ ...current, text_field: event.target.value }))}
                        className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm"
                      >
                        <option value="">請選擇</option>
                        {columns.map(column => <option key={column} value={column}>{column}</option>)}
                      </select>
                    </div>

                    <div className="space-y-1.5">
                      <Label>資料 ID</Label>
                      <p className="text-xs text-muted-foreground">用來對回來源資料；沒有固定 ID 可以不指定。</p>
                      <select
                        value={mapping.id_field || ''}
                        onChange={event => setMapping(current => ({ ...current, id_field: event.target.value || null }))}
                        className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm"
                      >
                        <option value="">不指定</option>
                        {columns.map(column => <option key={column} value={column}>{column}</option>)}
                      </select>
                    </div>

                    <div className="space-y-1.5">
                      <Label>原始標籤欄位（可選）</Label>
                      <p className="text-xs text-muted-foreground">如果檔案本身已有人工標籤，可在這裡保留為 source labels；沒有就留空。</p>
                      <select
                        value={mapping.labels?.field || ''}
                        onChange={event => setMapping(current => ({
                          ...current,
                          labels: event.target.value ? { field: event.target.value, format: 'single', delimiter: null } : null,
                        }))}
                        className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm"
                      >
                        <option value="">沒有既有標籤</option>
                        {columns.map(column => <option key={column} value={column}>{column}</option>)}
                      </select>
                    </div>

                    {mapping.labels && (
                      <div className="space-y-3 rounded-xl border border-border bg-muted/20 p-4">
                        <div className="space-y-1.5">
                          <Label>原始標籤格式</Label>
                          <select
                            value={mapping.labels.format}
                            onChange={event => setMapping(current => ({
                              ...current,
                              labels: current.labels
                                ? { ...current.labels, format: event.target.value as 'single' | 'delimiter' | 'json' }
                                : null,
                            }))}
                            className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm"
                          >
                            <option value="single">單一值</option>
                            <option value="delimiter">分隔字串</option>
                            <option value="json">JSON array</option>
                          </select>
                        </div>
                        {mapping.labels.format === 'delimiter' && (
                          <div className="space-y-1.5">
                            <Label>分隔符號</Label>
                            <Input
                              value={mapping.labels.delimiter || ','}
                              onChange={event => setMapping(current => ({
                                ...current,
                                labels: current.labels ? { ...current.labels, delimiter: event.target.value } : null,
                              }))}
                              placeholder=","
                            />
                          </div>
                        )}
                      </div>
                    )}

                    <div className="space-y-3 rounded-xl border border-border p-4">
                      <div>
                        <p className="text-sm font-medium">模型參考欄位（Context）</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          這些欄位會一起提供給 AI，只有可能影響分類判斷的資訊才需要勾選。
                        </p>
                      </div>
                      <FieldCheckList
                        columns={auxiliaryColumns}
                        selected={mapping.context_fields}
                        onToggle={column => setMapping(current => ({
                          ...current,
                          context_fields: toggleValue(current.context_fields, column),
                        }))}
                      />
                    </div>

                    <div className="space-y-3 rounded-xl border border-border p-4">
                      <div>
                        <p className="text-sm font-medium">其他資料欄位（Metadata）</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          只跟著資料保存，用於追蹤、篩選或匯出，預設不會送給 AI。單純文字分類可以完全不勾。
                        </p>
                      </div>
                      <FieldCheckList
                        columns={auxiliaryColumns}
                        selected={mapping.metadata_fields}
                        onToggle={column => setMapping(current => ({
                          ...current,
                          metadata_fields: toggleValue(current.metadata_fields, column),
                        }))}
                      />
                    </div>
                  </div>
                </section>

                <div className="border-t border-border" />

                <section className="space-y-4">
                  <SectionHeader
                    number={4}
                    title="標籤 Schema"
                    description="建立這個專案允許的標籤。需要階層時，再替標籤指定 Parent。"
                  />
                  <div className="space-y-5 pl-10">
                    <div className="space-y-1.5">
                      <Label>分類模式</Label>
                      <select
                        value={mode}
                        onChange={event => setMode(event.target.value as 'single_label' | 'multi_label')}
                        className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm"
                      >
                        <option value="multi_label">多選</option>
                        <option value="single_label">單選</option>
                      </select>
                    </div>

                    <div className="space-y-1.5">
                      <Label>最多標籤數</Label>
                      <Input
                        type="number"
                        min={1}
                        value={maxLabels}
                        onChange={event => setMaxLabels(event.target.value)}
                        placeholder="不限"
                      />
                    </div>

                    <label className="flex items-start gap-2 rounded-xl border border-border p-4 text-sm">
                      <input
                        className="mt-1"
                        type="checkbox"
                        checked={childRequiresParent}
                        onChange={event => setChildRequiresParent(event.target.checked)}
                      />
                      <span>
                        <span className="font-medium">子標籤必須包含父標籤</span>
                        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                          例如選到「配送延遲」時，結果也必須包含它的父標籤「物流」。
                        </span>
                      </span>
                    </label>

                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium">標籤清單</p>
                          <p className="mt-1 text-xs text-muted-foreground">每個標籤獨立一張卡片，從上到下設定即可。</p>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => addLabel(null)}>+ 新增標籤</Button>
                      </div>

                      <div className="space-y-3">
                        {labels.map((label, index) => (
                          <div key={`${label.id}-${index}`} className="space-y-4 rounded-xl border border-border p-4">
                            <div className="flex items-center justify-between">
                              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">標籤 {index + 1}</p>
                              <Button variant="ghost" size="sm" onClick={() => removeLabel(index)} disabled={labels.length <= 1}>
                                移除
                              </Button>
                            </div>
                            <div className="space-y-1.5">
                              <Label>顯示名稱</Label>
                              <Input value={label.name} onChange={event => updateLabelName(index, event.target.value)} placeholder="例：物流" />
                            </div>
                            <div className="space-y-1.5">
                              <Label>Label ID</Label>
                              <Input
                                className="font-mono text-xs"
                                value={label.id}
                                onChange={event => updateLabel(index, { id: event.target.value.trim() })}
                                placeholder="shipping"
                              />
                            </div>
                            <div className="space-y-1.5">
                              <Label>Parent</Label>
                              <select
                                className="h-10 w-full rounded-md border border-input bg-card px-3 text-sm"
                                value={label.parent_id || ''}
                                onChange={event => updateLabel(index, { parent_id: event.target.value || null })}
                                disabled={mode === 'single_label'}
                              >
                                <option value="">頂層標籤</option>
                                {labels.filter((_, i) => i !== index).map(parent => (
                                  <option key={parent.id} value={parent.id}>{parent.name}</option>
                                ))}
                              </select>
                            </div>
                            <div className="space-y-1.5">
                              <Label>標籤說明（可選）</Label>
                              <Input
                                value={label.description}
                                onChange={event => updateLabel(index, { description: event.target.value })}
                                placeholder="描述什麼情況應該使用這個標籤"
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {parentsWithChildren.length > 0 && (
                      <div className="space-y-3 rounded-xl border border-border p-4">
                        <div>
                          <p className="text-sm font-medium">父標籤的子標籤要求</p>
                          <p className="mt-1 text-xs leading-5 text-muted-foreground">
                            勾選後，只要選到該父標籤，就必須至少再選一個直接子標籤。
                          </p>
                        </div>
                        <FieldCheckList
                          columns={parentsWithChildren.map(parent => parent.id)}
                          selected={requireChildFor}
                          onToggle={id => setRequireChildFor(current => toggleValue(current, id))}
                        />
                      </div>
                    )}
                  </div>
                </section>

                <div className="border-t border-border" />

                <section className="space-y-4">
                  <SectionHeader
                    number={5}
                    title="標註規則"
                    description="補充相關性與專案指示，這些規則會套用到 LLM 與人工標註流程。"
                  />
                  <div className="space-y-5 pl-10">
                    <label className="flex items-start gap-2 rounded-xl border border-border p-4 text-sm">
                      <input
                        className="mt-1"
                        type="checkbox"
                        checked={relevanceEnabled}
                        onChange={event => setRelevanceEnabled(event.target.checked)}
                      />
                      <span>
                        <span className="font-medium">啟用相關性判斷</span>
                        <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                          如果每筆資料都一定要分類，可關閉；需要先判斷「相關 / 無關」時再開啟。
                        </span>
                      </span>
                    </label>

                    {relevanceEnabled && (
                      <div className="space-y-4 rounded-xl border border-border bg-muted/20 p-4">
                        <div className="space-y-1.5">
                          <Label>Relevant 顯示名稱</Label>
                          <Input value={relevantName} onChange={event => setRelevantName(event.target.value)} />
                        </div>
                        <div className="space-y-1.5">
                          <Label>Irrelevant 顯示名稱</Label>
                          <Input value={irrelevantName} onChange={event => setIrrelevantName(event.target.value)} />
                        </div>
                      </div>
                    )}

                    <div className="space-y-1.5">
                      <Label>標註規則 / Instructions</Label>
                      <p className="text-xs leading-5 text-muted-foreground">
                        寫下模型應如何判斷標籤、遇到模糊案例怎麼處理，以及任何 domain-specific 規則。
                      </p>
                      <textarea
                        value={instructions}
                        onChange={event => setInstructions(event.target.value)}
                        rows={6}
                        placeholder="例：依照使用者主要希望客服處理的問題分類；若同時涉及配送與退款可複選。"
                        className="w-full resize-y rounded-lg border border-input bg-card px-3 py-2 text-sm"
                      />
                    </div>
                  </div>
                </section>

                <div className="border-t border-border" />

                <section className="space-y-4 pb-2">
                  <SectionHeader
                    number={6}
                    title="確認建立"
                    description="最後確認主要設定。原始資料會完整保留，不會因標註結果而被覆寫。"
                  />
                  <div className="space-y-4 pl-10">
                    <div className="space-y-2 rounded-xl border border-border p-4 text-sm">
                      <p className="font-medium">資料 Mapping</p>
                      <p><span className="text-muted-foreground">主要文字：</span>{mapping.text_field || '尚未指定'}</p>
                      <p><span className="text-muted-foreground">ID：</span>{mapping.id_field || '不指定'}</p>
                      <p><span className="text-muted-foreground">Context：</span>{mapping.context_fields.join(', ') || '無'}</p>
                      <p><span className="text-muted-foreground">Metadata：</span>{mapping.metadata_fields.join(', ') || '無'}</p>
                    </div>

                    <div className="space-y-2 rounded-xl border border-border p-4 text-sm">
                      <p className="font-medium">標籤規則</p>
                      <p>{mode === 'multi_label' ? '多選' : '單選'} · {labels.length} 個標籤</p>
                      <p><span className="text-muted-foreground">最多：</span>{maxLabels || '不限'}</p>
                      <p><span className="text-muted-foreground">相關性：</span>{relevanceEnabled ? `${relevantName} / ${irrelevantName}` : '停用'}</p>
                    </div>

                    <div className="rounded-xl border border-border p-4">
                      <p className="mb-3 text-sm font-medium">Schema 預覽</p>
                      <div className="space-y-1.5 text-sm">
                        {labels.map(label => (
                          <div
                            key={label.id}
                            style={{ paddingLeft: `${labels.some(parent => parent.id === label.parent_id) ? 20 : 0}px` }}
                          >
                            <span className="font-medium">{label.name}</span>
                            <span className="ml-2 font-mono text-xs text-muted-foreground">{label.id}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="rounded-xl bg-muted/40 p-4 text-sm leading-6 text-muted-foreground">
                      系統會保存完整 <span className="font-mono text-foreground">original_data</span>，並把{' '}
                      <span className="font-mono text-foreground">{mapping.text_field || '主要文字欄位'}</span> 寫入 canonical{' '}
                      <span className="font-mono text-foreground">rows.text</span>；不會改寫來源檔資料。
                    </div>
                  </div>
                </section>
              </>
            )}

            {error && (
              <div className="rounded-lg border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {error}
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="border-t border-border bg-background px-6 py-4">
          <div className="flex w-full items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {preview ? `${preview.row_count} 筆資料已讀取` : '先讀取資料後即可完成其餘設定'}
            </p>
            {preview && (
              <Button onClick={handleCreate} disabled={working}>
                {working ? '建立中…' : `建立 ${preview.row_count} 筆專案`}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
