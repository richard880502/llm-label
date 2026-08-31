import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, LLMSlotConfig, McpOAuthConnection, Project, Task } from '../api/client'
import LLMSettingsAdvancedModal from './LLMSettingsAdvancedModal'
import CodebookEditorDialog from './CodebookEditorDialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

interface Props {
  projectId: number
  open: boolean
  onClose: () => void
  onTasksChanged?: () => void
}

const ACTIVE_STATUSES = new Set(['pending', 'waiting_for_agent', 'running'])

const STATUS_LABEL: Record<Task['status'], string> = {
  pending: '等待中',
  waiting_for_agent: '等待 Agent',
  running: '執行中',
  done: '完成',
  failed: '失敗',
  cancelled: '已停止',
}

function modelName(config: LLMSlotConfig): string {
  return config.name || config.model || `模型 ${config.slot}`
}

function taskSource(task: Task, slots: LLMSlotConfig[]): string {
  if (task.execution_mode === 'mcp') {
    return task.executor_name === 'claude' ? 'Claude Code' : 'Codex / ChatGPT'
  }
  const config = slots.find(item => item.slot === task.slot)
  return config ? modelName(config) : `平台模型 ${task.slot ?? ''}`.trim()
}

function progress(task: Task): number {
  if (task.total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((task.processed / task.total) * 100)))
}

function TaskDock({
  tasks,
  slots,
  onStop,
  onDelete,
}: {
  tasks: Task[]
  slots: LLMSlotConfig[]
  onStop: (taskId: number) => Promise<void>
  onDelete: (taskId: number) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const active = tasks.filter(task => ACTIVE_STATUSES.has(task.status))
  const recent = tasks.filter(task => !ACTIVE_STATUSES.has(task.status)).slice(0, 12)
  const visible = [...active, ...recent]

  if (tasks.length === 0 || typeof document === 'undefined') return null

  return createPortal(
    <div className="fixed bottom-6 right-6 z-[80] flex flex-col items-end gap-2">
      {expanded && (
        <div className="mb-1 w-[min(22rem,calc(100vw-3rem))] overflow-hidden rounded-2xl border border-border bg-popover/95 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <p className="text-sm font-semibold">任務紀錄</p>
              <p className="text-xs text-muted-foreground">
                {active.length > 0 ? `${active.length} 個任務執行中` : '目前沒有執行中的任務'}
              </p>
            </div>
            <Button variant="ghost" size="xs" onClick={() => setExpanded(false)}>收起</Button>
          </div>

          <div className="max-h-[22rem] space-y-2 overflow-y-auto p-3">
            {visible.map(task => {
              const isActive = ACTIVE_STATUSES.has(task.status)
              const pct = progress(task)
              return (
                <div key={task.id} className="space-y-2 rounded-xl border border-border bg-card/70 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{taskSource(task, slots)}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">#{task.id} · {STATUS_LABEL[task.status]}</p>
                    </div>
                    <Badge variant={task.status === 'failed' ? 'destructive' : 'outline'} className="shrink-0 text-[11px]">
                      {task.processed}/{task.total}
                    </Badge>
                  </div>

                  {isActive && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{task.status === 'waiting_for_agent' ? '等待 Agent 連線' : '處理中'}</span>
                        <span className="font-mono">{pct}%</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )}

                  {task.error && !isActive && <p className="line-clamp-2 text-xs text-destructive">{task.error}</p>}

                  <div className="flex justify-end">
                    {isActive ? (
                      <Button variant="destructive" size="xs" onClick={() => onStop(task.id)}>停止</Button>
                    ) : (
                      <Button variant="ghost" size="xs" className="text-destructive hover:text-destructive" onClick={() => onDelete(task.id)}>刪除</Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => setExpanded(value => !value)}
        className="flex items-center gap-2 rounded-full border border-border bg-popover/95 px-4 py-2.5 text-sm font-medium shadow-xl backdrop-blur-xl transition hover:bg-accent"
      >
        <span className={`h-2 w-2 rounded-full ${active.length > 0 ? 'bg-primary animate-pulse' : 'bg-muted-foreground/40'}`} />
        <span>任務紀錄</span>
        {active.length > 0 ? (
          <Badge variant="secondary" className="h-5 min-w-5 justify-center px-1.5">{active.length}</Badge>
        ) : (
          <span className="text-xs text-muted-foreground">{Math.min(tasks.length, 50)}</span>
        )}
        <span className="text-xs text-muted-foreground">{expanded ? '▼' : '▲'}</span>
      </button>
    </div>,
    document.body,
  )
}

export default function LLMSettingsModal({ projectId: pid, open, onClose, onTasksChanged }: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [codebookOpen, setCodebookOpen] = useState(false)
  const [slots, setSlots] = useState<LLMSlotConfig[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [mcpConnections, setMcpConnections] = useState<McpOAuthConnection[]>([])

  const [annotationInstructions, setAnnotationInstructions] = useState('')
  const [savedAnnotationInstructions, setSavedAnnotationInstructions] = useState('')
  const [savingInstructions, setSavingInstructions] = useState(false)
  const [instructionsMessage, setInstructionsMessage] = useState<string | null>(null)

  const [executionMode, setExecutionMode] = useState<'api' | 'mcp'>('api')
  const [taskTarget, setTaskTarget] = useState<'pending' | 'all' | 'parse_failed'>('pending')
  const [primarySlot, setPrimarySlot] = useState(1)
  const [compareModels, setCompareModels] = useState(false)
  const [compareSlots, setCompareSlots] = useState<number[]>([])
  const [mcpAgent, setMcpAgent] = useState<'codex' | 'claude'>('codex')
  const [mcpSlot, setMcpSlot] = useState(1)
  const [starting, setStarting] = useState(false)
  const [taskError, setTaskError] = useState<string | null>(null)
  const [createdMcpTask, setCreatedMcpTask] = useState<Task | null>(null)
  const [copied, setCopied] = useState(false)

  const configuredSlots = useMemo(
    () => slots.filter(item => Boolean(item.api_url && item.model)),
    [slots],
  )
  const activeTasks = useMemo(
    () => tasks.filter(task => ACTIVE_STATUSES.has(task.status)),
    [tasks],
  )
  const codebookDirty = annotationInstructions !== savedAnnotationInstructions

  const refreshTasks = async (notify = false) => {
    try {
      setTasks(await api.listTasks(pid))
      if (notify) onTasksChanged?.()
    } catch {
      // Keep the current task list if polling temporarily fails.
    }
  }

  const loadWorkspace = async () => {
    const [configsResult, projectResult, connectionsResult] = await Promise.allSettled([
      api.getLLMConfigs(pid),
      api.getProject(pid),
      api.listMcpOAuthConnections(),
    ])

    if (configsResult.status === 'fulfilled') {
      const configs = configsResult.value
      setSlots(configs)
      const configured = configs.filter(item => item.api_url && item.model)
      if (configured.length > 0) {
        setPrimarySlot(current => configured.some(item => item.slot === current) ? current : configured[0].slot)
        setCompareSlots(current => {
          const valid = current.filter(slot => configured.some(item => item.slot === slot))
          return valid.length > 0 ? valid : [configured[0].slot]
        })
      } else {
        setCompareSlots([])
      }
    }

    if (projectResult.status === 'fulfilled') {
      const currentProject = projectResult.value
      setProject(currentProject)
      setAnnotationInstructions(currentProject.annotation_instructions || '')
      setSavedAnnotationInstructions(currentProject.annotation_instructions || '')
    }

    if (connectionsResult.status === 'fulfilled') setMcpConnections(connectionsResult.value)
    await refreshTasks()
  }

  useEffect(() => {
    if (!open) {
      setAdvancedOpen(false)
      setCodebookOpen(false)
      setCreatedMcpTask(null)
      setTaskError(null)
      return
    }
    if (!advancedOpen) loadWorkspace()
  }, [open, advancedOpen, pid])

  useEffect(() => {
    if (!open || advancedOpen || activeTasks.length === 0) return
    const timer = window.setInterval(() => refreshTasks(), 2500)
    return () => window.clearInterval(timer)
  }, [open, advancedOpen, activeTasks.length, pid])

  const saveInstructions = async () => {
    if (!codebookDirty) return
    setSavingInstructions(true)
    setInstructionsMessage(null)
    try {
      const result = await api.updateAnnotationInstructions(pid, annotationInstructions)
      setAnnotationInstructions(result.annotation_instructions)
      setSavedAnnotationInstructions(result.annotation_instructions)
      setInstructionsMessage('已儲存，下一個分類任務會使用這版規則。')
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setInstructionsMessage(`儲存失敗：${message}`)
      throw error
    } finally {
      setSavingInstructions(false)
    }
  }

  const startApiTask = async () => {
    const requestedSlots = compareModels ? compareSlots : [primarySlot]
    const runnable = requestedSlots.filter(slot =>
      configuredSlots.some(item => item.slot === slot)
      && !activeTasks.some(task => task.slot === slot),
    )
    if (runnable.length === 0) return

    setStarting(true)
    setTaskError(null)
    try {
      if (codebookDirty) await saveInstructions()
      for (const slot of runnable) {
        const config = configuredSlots.find(item => item.slot === slot)
        await api.createTask(pid, {
          target: taskTarget,
          slot,
          execution_mode: 'api',
          executor_name: config ? modelName(config) : `模型 ${slot}`,
        })
      }
      await refreshTasks(true)
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : String(error))
    } finally {
      setStarting(false)
    }
  }

  const startMcpTask = async () => {
    if (activeTasks.some(task => task.slot === mcpSlot)) return
    setStarting(true)
    setTaskError(null)
    setCreatedMcpTask(null)
    try {
      if (codebookDirty) await saveInstructions()
      const task = await api.createTask(pid, {
        target: taskTarget,
        slot: mcpSlot,
        execution_mode: 'mcp',
        executor_name: mcpAgent,
      })
      setCreatedMcpTask(task)
      await refreshTasks(true)
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : String(error))
    } finally {
      setStarting(false)
    }
  }

  const stopTask = async (taskId: number) => {
    if (!window.confirm('確定停止這個分類任務？')) return
    try {
      await api.cancelTask(pid, taskId)
      await refreshTasks(true)
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : String(error))
    }
  }

  const deleteTask = async (taskId: number) => {
    if (!window.confirm('確定刪除這筆任務紀錄？')) return
    try {
      await api.deleteTask(pid, taskId)
      await refreshTasks(true)
    } catch (error) {
      setTaskError(error instanceof Error ? error.message : String(error))
    }
  }

  const copyRunInstruction = async () => {
    if (!createdMcpTask) return
    const text = `請執行標注平台 project ${pid} 的分類任務 #${createdMcpTask.id}。先 claim_labeling_task，接著反覆取得並提交批次，直到任務完成。`
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setTaskError('自動複製失敗，請手動選取任務指令。')
    }
  }

  const toggleCompareSlot = (slot: number) => {
    setCompareSlots(current => {
      if (current.includes(slot)) {
        const next = current.filter(item => item !== slot)
        return next.length > 0 ? next : current
      }
      return [...current, slot]
    })
  }

  if (advancedOpen) {
    return (
      <LLMSettingsAdvancedModal
        projectId={pid}
        open={open}
        onClose={() => setAdvancedOpen(false)}
        onTasksChanged={onTasksChanged}
      />
    )
  }

  return (
    <>
      <Dialog open={open} onOpenChange={value => { if (!value) onClose() }}>
        <DialogContent className="sm:max-w-3xl h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
          <DialogHeader className="shrink-0 border-b px-6 py-4">
            <div className="flex items-start justify-between gap-4 pr-8">
              <div>
                <DialogTitle>自動分類</DialogTitle>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  先確認分類規則，再選擇平台模型或 MCP Agent 執行。Codebook 有修改時，開始任務前會自動儲存。
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setAdvancedOpen(true)}>
                進階設定
              </Button>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-6 py-5">
            <button
              type="button"
              onClick={() => setCodebookOpen(true)}
              className="group w-full rounded-2xl border border-teal-200 bg-teal-50/40 p-4 text-left transition hover:border-teal-400 hover:bg-teal-50/70 dark:border-teal-900 dark:bg-teal-950/10 dark:hover:border-teal-700 dark:hover:bg-teal-950/20"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold">1. 分類規則 / Codebook</p>
                    <span className="text-xs text-teal-700 opacity-0 transition-opacity group-hover:opacity-100 dark:text-teal-300">點擊完整編輯 →</span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    平台 API 與 MCP Agent 共用同一份規則；目前有 {project?.corrected || 0} 筆人工修正案例可供 Few-shot 使用。
                  </p>
                </div>
                <Badge variant={codebookDirty ? 'outline' : 'secondary'}>{codebookDirty ? '尚未儲存' : '已儲存'}</Badge>
              </div>

              <div className="mt-3 rounded-xl border border-teal-200/70 bg-card/70 px-3 py-2.5 dark:border-teal-900/70">
                {annotationInstructions.trim() ? (
                  <p className="line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-foreground/80">{annotationInstructions}</p>
                ) : (
                  <p className="text-sm text-muted-foreground">尚未撰寫規則。點擊這個區域開始建立 Codebook。</p>
                )}
              </div>

              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{annotationInstructions.length.toLocaleString()} / 12,000 字元{codebookDirty ? ' · 開始分類時會自動儲存' : ''}</span>
                <span className="font-medium text-teal-700 dark:text-teal-300">開啟完整 Codebook 編輯器</span>
              </div>
              {instructionsMessage && (
                <p className={`mt-2 text-xs ${instructionsMessage.startsWith('儲存失敗') ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}`}>
                  {instructionsMessage}
                </p>
              )}
            </button>

            <section className="space-y-4 rounded-2xl border border-border p-4">
              <div>
                <p className="text-sm font-semibold">2. 執行分類</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  選擇這次要由平台背景模型執行，或交給已連線的 Codex / ChatGPT / Claude Code Agent。
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setExecutionMode('api')}
                  className={`rounded-xl border p-4 text-left transition-colors ${executionMode === 'api' ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border hover:bg-muted/40'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">平台模型 API</span>
                    <Badge variant="secondary">背景執行</Badge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">由平台直接呼叫已設定的模型，關閉頁面後仍會繼續。</p>
                </button>

                <button
                  type="button"
                  onClick={() => setExecutionMode('mcp')}
                  className={`rounded-xl border p-4 text-left transition-colors ${executionMode === 'mcp' ? 'border-violet-500 bg-violet-500/5 ring-1 ring-violet-500/20' : 'border-border hover:bg-muted/40'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">MCP Agent</span>
                    <Badge variant="outline">Codex / Claude</Badge>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">建立可由外部 Agent claim 的分類任務，使用自己的 Agent 執行。</p>
                </button>
              </div>

              <div className="space-y-2">
                <Label className="text-xs font-medium">資料範圍</Label>
                <RadioGroup
                  value={taskTarget}
                  onValueChange={value => setTaskTarget(value as 'pending' | 'all' | 'parse_failed')}
                  className="grid gap-2 sm:grid-cols-3"
                >
                  <label htmlFor="run-target-pending" className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${taskTarget === 'pending' ? 'border-primary bg-primary/5' : 'border-border'}`}>
                    <RadioGroupItem id="run-target-pending" value="pending" className="mt-0.5" />
                    <span>
                      <span className="block text-sm font-medium">只分類待審資料</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">目前約 {project?.pending ?? '—'} 筆，不重跑已審查資料。</span>
                    </span>
                  </label>
                  <label htmlFor="run-target-parse-failed" className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${taskTarget === 'parse_failed' ? 'border-rose-400 bg-rose-50/50 dark:bg-rose-950/10' : 'border-border'}`}>
                    <RadioGroupItem id="run-target-parse-failed" value="parse_failed" className="mt-0.5" />
                    <span>
                      <span className="block text-sm font-medium">只重跑失敗</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">依選擇的結果位置，只重跑所有標記為失敗的結果，例如解析失敗、HTTP / 429、timeout 或其他 LLM 呼叫失敗。</span>
                    </span>
                  </label>
                  <label htmlFor="run-target-all" className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${taskTarget === 'all' ? 'border-amber-400 bg-amber-50/50 dark:bg-amber-950/10' : 'border-border'}`}>
                    <RadioGroupItem id="run-target-all" value="all" className="mt-0.5" />
                    <span>
                      <span className="block text-sm font-medium">重新分類全部資料</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">會重新產生 AI prediction，但不直接覆蓋人工最終結果。</span>
                    </span>
                  </label>
                </RadioGroup>
              </div>

              {executionMode === 'api' ? (
                <div className="space-y-4 rounded-xl bg-muted/30 p-4">
                  {configuredSlots.length === 0 ? (
                    <div className="space-y-2 text-sm">
                      <p className="font-medium">尚未設定平台模型</p>
                      <p className="text-xs text-muted-foreground">先到進階設定新增 API URL、模型與必要的 API Key。</p>
                      <Button variant="outline" size="sm" onClick={() => setAdvancedOpen(true)}>設定平台模型</Button>
                    </div>
                  ) : (
                    <>
                      <div className="space-y-2">
                        <Label className="text-xs font-medium">模型</Label>
                        {!compareModels ? (
                          <Select value={String(primarySlot)} onValueChange={value => setPrimarySlot(Number(value || configuredSlots[0].slot))}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                            <SelectContent>
                              {configuredSlots.map(config => (
                                <SelectItem key={config.slot} value={String(config.slot)}>{modelName(config)} · {config.model}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <div className="space-y-2">
                            {configuredSlots.map(config => {
                              const checked = compareSlots.includes(config.slot)
                              const running = activeTasks.some(task => task.slot === config.slot)
                              return (
                                <label key={config.slot} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 ${checked ? 'border-primary bg-primary/5' : 'border-border'}`}>
                                  <input type="checkbox" checked={checked} disabled={running} onChange={() => toggleCompareSlot(config.slot)} />
                                  <span className="min-w-0 flex-1">
                                    <span className="block truncate text-sm font-medium">{modelName(config)}</span>
                                    <span className="block truncate text-xs text-muted-foreground">{config.model}{running ? ' · 執行中' : ''}</span>
                                  </span>
                                </label>
                              )
                            })}
                          </div>
                        )}
                      </div>

                      {configuredSlots.length > 1 && (
                        <label className="flex cursor-pointer items-start gap-2 text-sm">
                          <input type="checkbox" className="mt-1" checked={compareModels} onChange={event => setCompareModels(event.target.checked)} />
                          <span>
                            <span className="font-medium">比較多個模型</span>
                            <span className="block text-xs text-muted-foreground">同一批資料分別建立多個任務，結果會保存在不同結果位置。</span>
                          </span>
                        </label>
                      )}

                      <div className="flex justify-end">
                        <Button onClick={startApiTask} disabled={starting || configuredSlots.length === 0}>
                          {starting ? '啟動中…' : compareModels ? `開始 ${compareSlots.length} 個模型分類` : '開始背景分類'}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div className="space-y-4 rounded-xl border border-violet-200 bg-violet-50/40 p-4 dark:border-violet-900 dark:bg-violet-950/10">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-2">
                      <Label className="text-xs font-medium">Agent</Label>
                      <Select value={mcpAgent} onValueChange={value => setMcpAgent((value || 'codex') as 'codex' | 'claude')}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="codex">Codex / ChatGPT</SelectItem>
                          <SelectItem value="claude">Claude Code</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs font-medium">結果位置</Label>
                      <Select value={String(mcpSlot)} onValueChange={value => setMcpSlot(Number(value || 1))}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {[1, 2, 3].map(slot => {
                            const config = slots.find(item => item.slot === slot)
                            return (
                              <SelectItem key={slot} value={String(slot)}>
                                結果 {slot}{config ? ` · ${modelName(config)}` : ''}
                              </SelectItem>
                            )
                          })}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card/70 px-3 py-2.5">
                    <div>
                      <p className="text-sm font-medium">MCP 連線</p>
                      <p className="text-xs text-muted-foreground">GUI OAuth 目前偵測到 {mcpConnections.length} 個連線；CLI Agent 也可以使用既有 access token。</p>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => setAdvancedOpen(true)}>管理連線</Button>
                  </div>

                  <div className="flex justify-end">
                    <Button onClick={startMcpTask} disabled={starting || activeTasks.some(task => task.slot === mcpSlot)}>
                      {starting ? '建立中…' : `建立 ${mcpAgent === 'codex' ? 'Codex' : 'Claude Code'} 分類任務`}
                    </Button>
                  </div>

                  {createdMcpTask && (
                    <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/20">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium">任務 #{createdMcpTask.id} 已建立</p>
                        <Badge variant="outline">等待 Agent</Badge>
                      </div>
                      <p className="text-xs leading-5 text-muted-foreground">把下列指令交給 Agent，它會 claim 任務並持續提交分類結果。</p>
                      <div className="flex items-start gap-2">
                        <textarea
                          readOnly
                          rows={3}
                          value={`請執行標注平台 project ${pid} 的分類任務 #${createdMcpTask.id}。先 claim_labeling_task，接著反覆取得並提交批次，直到任務完成。`}
                          className="min-w-0 flex-1 rounded-md border bg-card px-3 py-2 text-xs"
                        />
                        <Button variant="outline" size="sm" onClick={copyRunInstruction}>{copied ? '已複製' : '複製'}</Button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {taskError && <p className="text-sm text-destructive">{taskError}</p>}
            </section>

            <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-muted/30 p-4">
              <div>
                <p className="text-sm font-medium">模型、Prompt、Few-shot 或 MCP 連線</p>
                <p className="mt-1 text-xs text-muted-foreground">這些低頻設定集中在進階設定；完整任務紀錄也在同一處。</p>
              </div>
              <Button variant="outline" onClick={() => setAdvancedOpen(true)}>開啟進階設定</Button>
            </section>
          </div>

          <DialogFooter className="shrink-0 border-t px-6 py-3">
            <Button variant="outline" onClick={onClose}>關閉</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CodebookEditorDialog
        open={codebookOpen}
        onOpenChange={setCodebookOpen}
        value={annotationInstructions}
        onChange={value => {
          setAnnotationInstructions(value)
          setInstructionsMessage(null)
        }}
        correctedExamples={project?.corrected || 0}
        dirty={codebookDirty}
        saving={savingInstructions}
        message={instructionsMessage}
        onSave={saveInstructions}
      />

      {open && !codebookOpen && (
        <TaskDock tasks={tasks} slots={slots} onStop={stopTask} onDelete={deleteTask} />
      )}
    </>
  )
}
