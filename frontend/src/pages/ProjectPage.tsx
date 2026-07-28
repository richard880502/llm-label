import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, LLMSlotConfig } from '../api/client'
import HeaderUserMenu from '../components/HeaderUserMenu'
import LLMSettingsModal from '../components/LLMSettingsModal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Label } from '@/components/ui/label'

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  pending:   { label: '待審',   cls: 'bg-muted text-muted-foreground' },
  approved:  { label: '已核准', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
  corrected: { label: '已修正', cls: 'bg-primary/10 text-primary' },
  uncertain: { label: '未確定', cls: 'bg-orange-500/20 text-orange-700 ring-1 ring-inset ring-orange-500/25 dark:bg-orange-500/20 dark:text-orange-300' },
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query || !text) return <>{text}</>
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === query.toLowerCase()
          ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700/50 text-foreground rounded-sm px-0.5 not-italic">{part}</mark>
          : part
      )}
    </>
  )
}

function parseLabels(val: string | null): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return val.split(',').map(s => s.trim()).filter(Boolean) }
}

function BulkAdoptModal({ projectId, adoptOpen, setAdoptOpen, onDone }: {
  projectId: number
  adoptOpen: boolean
  setAdoptOpen: (open: boolean) => void
  onDone: () => void
}) {
  const [slots, setSlots] = useState<LLMSlotConfig[]>([])
  const [selectedSlot, setSelectedSlot] = useState(1)
  const [target, setTarget] = useState<'pending' | 'all'>('pending')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<number | null>(null)

  useEffect(() => {
    api.getLLMConfigs(projectId).then(setSlots).catch(() => {})
  }, [projectId])
  useEffect(() => { if (!adoptOpen) setTimeout(() => setResult(null), 200) }, [adoptOpen])

  const handleApply = async () => {
    setLoading(true)
    try {
      const r = await api.adoptSlot(projectId, selectedSlot, target)
      setResult(r.updated)
      onDone()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '發生錯誤')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={adoptOpen} onOpenChange={(o) => setAdoptOpen(o)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>一鍵套用 LLM 結果</DialogTitle>
        </DialogHeader>
        {result !== null ? (
          <div className="flex flex-col items-center py-6 gap-3">
            <div className="w-12 h-12 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center text-emerald-600 dark:text-emerald-400 text-2xl">✓</div>
            <p className="text-foreground text-sm">已套用 <span className="font-semibold text-primary">{result}</span> 筆資料</p>
            <Button onClick={() => setAdoptOpen(false)} className="mt-2">關閉</Button>
          </div>
        ) : (
          <>
            <div className="space-y-5 py-1">
              <div className="space-y-2">
                <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">LLM 來源</Label>
                <RadioGroup value={String(selectedSlot)} onValueChange={val => setSelectedSlot(Number(val))}>
                  <div className="space-y-1.5">
                    {slots.map(s => (
                      <label key={s.slot} htmlFor={`slot-${s.slot}`}
                        className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors ${selectedSlot === s.slot ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}>
                        <RadioGroupItem value={String(s.slot)} id={`slot-${s.slot}`} />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-foreground">{s.name}</div>
                          {s.model && <div className="text-xs text-muted-foreground truncate">{s.model}</div>}
                        </div>
                      </label>
                    ))}
                  </div>
                </RadioGroup>
              </div>
              <div className="space-y-2">
                <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">套用範圍</Label>
                <RadioGroup value={target} onValueChange={val => setTarget(val as 'pending' | 'all')}>
                  <div className="space-y-1.5">
                    <label htmlFor="target-pending"
                      className={`flex items-start gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors ${target === 'pending' ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50'}`}>
                      <RadioGroupItem value="pending" id="target-pending" className="mt-0.5" />
                      <div>
                        <div className="text-sm font-medium text-foreground">只套用未審查</div>
                        <div className="text-xs text-muted-foreground">不覆蓋已手動審查的資料</div>
                      </div>
                    </label>
                    <label htmlFor="target-all"
                      className={`flex items-start gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors ${target === 'all' ? 'border-destructive bg-destructive/5' : 'border-border hover:bg-muted/50'}`}>
                      <RadioGroupItem value="all" id="target-all" className="mt-0.5" />
                      <div>
                        <div className="text-sm font-medium text-foreground">套用至全部資料</div>
                        <div className="text-xs text-destructive">會覆蓋已手動審查的資料</div>
                      </div>
                    </label>
                  </div>
                </RadioGroup>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setAdoptOpen(false)}>取消</Button>
              <Button onClick={handleApply} disabled={loading}>
                {loading ? '套用中…' : '確認套用'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const pid = Number(projectId)

  const status      = searchParams.get('status')      || 'all'
  const relevance   = searchParams.get('relevance')   || 'all'
  const disagreement = searchParams.get('disagreement') || 'all'
  const q           = searchParams.get('q')           || ''
  const page        = Number(searchParams.get('page') || 1)

  const setFilter = (key: string, value: string, resetPage = true) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set(key, value)
      if (resetPage) next.set('page', '1')
      return next
    })
  }

  const queryClient = useQueryClient()

  const { data: presence = [] } = useQuery({
    queryKey: ['presence', pid],
    queryFn: () => api.getPresence(pid),
    refetchInterval: 5000,
  })

  const invalidateProjectData = () => {
    queryClient.invalidateQueries({ queryKey: ['rows', pid] })
    queryClient.invalidateQueries({ queryKey: ['project', pid] })
  }

  function userColor(username: string) {
    const colors = ['#3b82f6','#8b5cf6','#10b981','#f97316','#ec4899','#14b8a6','#f59e0b','#f43f5e']
    let h = 0; for (const c of username) h = (h * 31 + c.charCodeAt(0)) & 0xffff
    return colors[h % colors.length]
  }

  const [llmOpen, setLlmOpen] = useState(false)
  const [adoptOpen, setAdoptOpen] = useState(false)
  const [qInput, setQInput] = useState(q)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [selectAllRows, setSelectAllRows] = useState(false)
  const [batchSaving, setBatchSaving] = useState(false)
  const selectAllRef = useRef<HTMLInputElement>(null)
  const PAGE_SIZE = 50

  const { data: tasks = [], refetch: refetchTasks } = useQuery({
    queryKey: ['tasks', pid],
    queryFn: () => api.listTasks(pid),
    refetchInterval: 4000,
  })
  const activeTasks = tasks.filter(t => ['pending', 'waiting_for_agent', 'running'].includes(t.status))

  const { data: project } = useQuery({
    queryKey: ['project', pid],
    queryFn: () => api.getProject(pid),
  })

  const { data: rowsData, isLoading: loading } = useQuery({
    queryKey: ['rows', pid, page, status, relevance, q, disagreement],
    queryFn: () => api.listRows(pid, { page, page_size: PAGE_SIZE, status, relevance, q, disagreement }),
  })
  const rows = rowsData?.items ?? []
  const total = rowsData?.total ?? 0

  useEffect(() => { setSelectedIds(new Set()) }, [rows])

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectedIds.size > 0 && selectedIds.size < rows.length
    }
  }, [selectedIds.size, rows.length])

  const toggleSelect = (id: number) => setSelectedIds(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  const toggleSelectAll = () => {
    setSelectAllRows(false)
    setSelectedIds(selectedIds.size === rows.length ? new Set() : new Set(rows.map(r => r.id)))
  }

  const batchApprove = async () => {
    setBatchSaving(true)
    try {
      if (selectAllRows) {
        await api.batchUpdateRows(pid, {
          select_all: true, status: 'approved',
          status_filter: status, relevance_filter: relevance,
          q_filter: q, disagreement_filter: disagreement,
        })
      } else {
        await api.batchUpdateRows(pid, { ids: [...selectedIds], status: 'approved' })
      }
      setSelectedIds(new Set())
      setSelectAllRows(false)
      invalidateProjectData()
    } catch (e) {
      alert(e instanceof Error ? e.message : '批次操作失敗')
    } finally {
      setBatchSaving(false)
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const goReview = (rowId: number) => navigate(`/projects/${pid}/review/${rowId}?${searchParams.toString()}`)

  return (
    <div className="min-h-screen">
      <header className="relative sticky top-0 z-40 backdrop-blur-2xl bg-white/45 dark:bg-black/25 border-b border-black/8 dark:border-white/8 shadow-sm shadow-black/5">
        <div className="max-w-6xl mx-auto px-6 py-2.5 flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => navigate('/')}
            className="text-muted-foreground shrink-0 px-2">← 返回</Button>
          <span className="text-border">／</span>
          <h1 className="text-sm font-semibold text-foreground truncate flex-1 min-w-0">{project?.name || '載入中…'}</h1>

          {project && (
            <div className="hidden sm:flex items-center gap-3 text-xs text-muted-foreground shrink-0 mr-1">
              <span className="text-emerald-600 dark:text-emerald-400 font-medium">✓ {project.approved || 0}</span>
              <span className="text-primary font-medium">✎ {project.corrected || 0}</span>
              <span className="text-orange-600 dark:text-orange-400 font-semibold">? {project.uncertain || 0}</span>
              <span>⏳ {project.pending ?? project.total_rows}</span>
              <span className="text-border">·</span>
              <span>{project.total_rows} 筆</span>
            </div>
          )}

          {project && (
            <div className="flex items-center gap-1.5 shrink-0">
              <Button variant="outline" size="sm"
                onClick={() => api.exportProject(pid, `${project.name}.xlsx`).catch(e => alert(e.message))}>
                匯出
              </Button>
              <Button variant="outline" size="sm" onClick={() => setAdoptOpen(true)}
                className="border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20">
                一鍵套用
              </Button>
              <Button variant="outline" size="sm" onClick={() => setLlmOpen(true)}
                className="border-violet-200 dark:border-violet-800 text-violet-700 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20">
                ⚙ 自動分類{activeTasks.length > 0 ? ` · ${activeTasks.length}` : ''}
              </Button>
            </div>
          )}
          <HeaderUserMenu />
        </div>
        {project && project.total_rows > 0 && (
          <div className="absolute bottom-0 left-0 right-0 h-0.5 overflow-hidden">
            <div className="h-full flex">
              <div className="h-full bg-emerald-500 transition-all duration-700"
                style={{ width: `${(project.approved || 0) / project.total_rows * 100}%` }} />
              <div className="h-full bg-primary transition-all duration-700"
                style={{ width: `${(project.corrected || 0) / project.total_rows * 100}%` }} />
              <div className="h-full bg-orange-500 transition-all duration-700"
                style={{ width: `${(project.uncertain || 0) / project.total_rows * 100}%` }} />
            </div>
          </div>
        )}
      </header>

      <main className="max-w-6xl mx-auto px-6 py-5">
        {/* Filters */}
        <div className="flex flex-wrap gap-2 mb-5">
          <Select value={status} onValueChange={val => setFilter('status', val ?? 'all')}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="狀態">
                {({'all':'所有狀態','pending':'待審','approved':'已核准','corrected':'已修正','uncertain':'未確定'} as Record<string,string>)[status]}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">所有狀態</SelectItem>
              <SelectItem value="pending">待審</SelectItem>
              <SelectItem value="approved">已核准</SelectItem>
              <SelectItem value="corrected">已修正</SelectItem>
              <SelectItem value="uncertain">未確定</SelectItem>
            </SelectContent>
          </Select>

          <Select value={relevance} onValueChange={val => setFilter('relevance', val ?? 'all')}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="相關性">
                {({'all':'所有相關性','相關':'相關','無關':'無關'} as Record<string,string>)[relevance]}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">所有相關性</SelectItem>
              <SelectItem value="相關">相關</SelectItem>
              <SelectItem value="無關">無關</SelectItem>
            </SelectContent>
          </Select>

          <Select value={disagreement} onValueChange={val => setFilter('disagreement', val ?? 'all')}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="歧異">
                {({'all':'所有狀態','first':'歧異優先','only':'只看歧異'} as Record<string,string>)[disagreement]}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">所有狀態</SelectItem>
              <SelectItem value="first">歧異優先</SelectItem>
              <SelectItem value="only">只看歧異</SelectItem>
            </SelectContent>
          </Select>

          <div className="flex flex-1 min-w-48">
            <Input value={qInput} onChange={e => setQInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') setFilter('q', qInput) }}
              placeholder="搜尋留言內容…"
              className="rounded-r-none border-r-0 focus-visible:ring-0 focus-visible:ring-offset-0" />
            <Button onClick={() => setFilter('q', qInput)} className="rounded-l-none shrink-0">搜尋</Button>
          </div>
          <span className="self-center text-sm text-muted-foreground">共 {total} 筆</span>
        </div>

        {/* Table */}
        <div className="bg-card rounded-2xl overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">載入中…</div>
          ) : rows.length === 0 ? (
            <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">沒有符合條件的資料</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-black/3 dark:bg-white/3">
                  <th className="px-4 py-3 w-10" onClick={e => e.stopPropagation()}>
                    <input ref={selectAllRef} type="checkbox"
                      checked={rows.length > 0 && selectedIds.size === rows.length}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 rounded cursor-pointer accent-primary" />
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground w-14">#</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">留言內容</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground w-20">相關性</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground">標籤</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground w-16">AI</th>
                  <th className="text-left px-4 py-3 font-medium text-muted-foreground w-22">狀態</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map(row => {
                  const eff = STATUS_LABELS[row.status] || STATUS_LABELS.pending
                  const relevanceVal = row.corrected_relevance ?? row.ai_relevance
                  const labels = parseLabels(row.corrected_labels ?? row.ai_labels)
                  return (
                    <tr key={row.id} onClick={() => goReview(row.id)}
                      className={`hover:bg-accent/50 cursor-pointer transition-colors group ${selectedIds.has(row.id) ? 'bg-primary/5' : ''}`}>
                      <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                        <input type="checkbox"
                          checked={selectedIds.has(row.id)}
                          onChange={() => toggleSelect(row.id)}
                          className="w-4 h-4 rounded cursor-pointer accent-primary" />
                      </td>
                      <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                        <div className="flex items-center gap-1.5">
                          <span>{row.source_row_number - 1}</span>
                          {presence.filter(p => p.row_id === row.id).map(p => (
                            <span key={p.username} title={p.username}
                              className="w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold text-white"
                              style={{ backgroundColor: userColor(p.username) }}>
                              {p.username[0].toUpperCase()}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-foreground max-w-xs">
                        <p className="truncate">
                          {row.comment_content
                            ? <Highlight text={row.comment_content} query={q} />
                            : <span className="text-muted-foreground/50 italic">（無留言）</span>}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          relevanceVal === '相關'
                            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                            : 'bg-muted text-muted-foreground'
                        }`}>{relevanceVal || '—'}</span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {labels.slice(0, 3).map(l => (
                            <span key={l} className="text-xs bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400 px-1.5 py-0.5 rounded">
                              {l.split(' ')[0]}
                            </span>
                          ))}
                          {labels.length > 3 && <span className="text-xs text-muted-foreground">+{labels.length - 3}</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {row.llm_parse_failed === 1 ? (
                          <Badge variant="outline" className="text-xs border-red-300 text-red-600 dark:text-red-400" title="LLM 回傳格式無法解析，請人工判斷">⚠ 解析失敗</Badge>
                        ) : row.llm_disagreement === 1 && !row.corrected_labels ? (
                          <Badge variant="outline" className="text-xs border-amber-300 text-amber-600 dark:text-amber-400">歧異</Badge>
                        ) : row.llm_updated_at && !row.corrected_labels ? (
                          <Badge variant="secondary" className="text-xs">LLM</Badge>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${eff.cls}`}>{eff.label}</span>
                        {row.reviewer_username && (
                          <p className="text-xs text-muted-foreground mt-0.5">{row.reviewer_username}</p>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-5">
            <Button variant="outline" size="sm" disabled={page <= 1}
              onClick={() => setFilter('page', String(page - 1), false)}>← 上一頁</Button>
            <span className="text-sm text-muted-foreground">第</span>
            <Input type="number" min={1} max={totalPages} defaultValue={page} key={page}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  const v = Math.max(1, Math.min(totalPages, Number((e.target as HTMLInputElement).value)))
                  setFilter('page', String(v), false)
                }
              }}
              onBlur={e => {
                const v = Math.max(1, Math.min(totalPages, Number(e.target.value)))
                if (v !== page) setFilter('page', String(v), false)
              }}
              className="w-14 text-center" />
            <span className="text-sm text-muted-foreground">/ {totalPages} 頁</span>
            <Button variant="outline" size="sm" disabled={page >= totalPages}
              onClick={() => setFilter('page', String(page + 1), false)}>下一頁 →</Button>
          </div>
        )}
      </main>

      <LLMSettingsModal projectId={pid} open={llmOpen} onClose={() => setLlmOpen(false)} onTasksChanged={() => refetchTasks()} />
      <BulkAdoptModal projectId={pid} adoptOpen={adoptOpen} setAdoptOpen={setAdoptOpen}
        onDone={invalidateProjectData} />

      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-foreground/90 backdrop-blur-sm text-background px-5 py-3 rounded-full shadow-xl text-sm">
          <span>已選 <span className="font-semibold">{selectAllRows ? total : selectedIds.size}</span> 筆</span>
          {!selectAllRows && selectedIds.size === rows.length && total > rows.length && (
            <>
              <div className="w-px h-4 bg-background/30" />
              <button onClick={() => setSelectAllRows(true)}
                className="hover:opacity-70 transition-opacity underline underline-offset-2">
                選取全部 {total} 筆
              </button>
            </>
          )}
          <div className="w-px h-4 bg-background/30" />
          <button onClick={batchApprove} disabled={batchSaving}
            className="font-semibold hover:opacity-70 transition-opacity disabled:opacity-40">
            {batchSaving ? '處理中…' : '批次核准'}
          </button>
          <div className="w-px h-4 bg-background/30" />
          <button onClick={() => { setSelectedIds(new Set()); setSelectAllRows(false) }}
            className="hover:opacity-70 transition-opacity">取消</button>
        </div>
      )}
    </div>
  )
}
