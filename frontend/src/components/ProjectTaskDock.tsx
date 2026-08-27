import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, Task } from '../api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

const ACTIVE_STATUSES = new Set<Task['status']>(['pending', 'waiting_for_agent', 'running'])

const STATUS_LABEL: Record<Task['status'], string> = {
  pending: '等待中',
  waiting_for_agent: '等待 Agent',
  running: '執行中',
  done: '完成',
  failed: '失敗',
  cancelled: '已停止',
}

function taskSource(task: Task): string {
  if (task.execution_mode === 'mcp') {
    return task.executor_name === 'claude' ? 'Claude Code' : 'Codex / ChatGPT'
  }
  return task.executor_name || `平台模型 ${task.slot ?? ''}`.trim()
}

function progress(task: Task): number {
  if (task.total <= 0) return 0
  return Math.max(0, Math.min(100, Math.round((task.processed / task.total) * 100)))
}

function collapsedSummary(active: Task[]): string {
  if (active.length === 0) return '任務紀錄'
  if (active.length > 1) return `${active.length} 個執行中`

  const task = active[0]
  if (task.status === 'waiting_for_agent') return '等待 Agent'
  if (task.status === 'pending') return '任務等待中'
  return `執行中 · ${progress(task)}%`
}

export default function ProjectTaskDock({ projectId }: { projectId: number }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [expanded, setExpanded] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const active = useMemo(
    () => tasks.filter(task => ACTIVE_STATUSES.has(task.status)),
    [tasks],
  )
  const recent = useMemo(
    () => tasks.filter(task => !ACTIVE_STATUSES.has(task.status)).slice(0, 12),
    [tasks],
  )
  const visible = useMemo(() => [...active, ...recent], [active, recent])

  const refresh = async () => {
    try {
      setTasks(await api.listTasks(projectId))
    } catch {
      // A temporary polling failure should not make the existing dock disappear.
    }
  }

  useEffect(() => {
    refresh()
    const timer = window.setInterval(refresh, 3000)
    return () => window.clearInterval(timer)
  }, [projectId])

  useEffect(() => {
    const updateDialogState = () => {
      setDialogOpen(Boolean(document.querySelector('[data-slot="dialog-content"]')))
    }
    updateDialogState()
    const observer = new MutationObserver(updateDialogState)
    observer.observe(document.body, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [])

  const stopTask = async (taskId: number) => {
    if (!window.confirm('確定停止這個分類任務？')) return
    setBusyTaskId(taskId)
    setError(null)
    try {
      await api.cancelTask(projectId, taskId)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyTaskId(null)
    }
  }

  const deleteTask = async (taskId: number) => {
    if (!window.confirm('確定刪除這筆任務紀錄？')) return
    setBusyTaskId(taskId)
    setError(null)
    try {
      await api.deleteTask(projectId, taskId)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyTaskId(null)
    }
  }

  if (typeof document === 'undefined' || dialogOpen || tasks.length === 0) return null

  return createPortal(
    <div className="fixed bottom-6 right-6 z-[70] flex flex-col items-end gap-2">
      {expanded && (
        <div className="mb-1 w-[min(23rem,calc(100vw-3rem))] overflow-hidden rounded-2xl border border-border bg-popover/95 shadow-2xl backdrop-blur-xl">
          <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold">任務紀錄</p>
                {active.length > 0 && (
                  <Badge variant="secondary" className="text-[11px]">{active.length} 執行中</Badge>
                )}
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">背景任務可在這裡停止，完成後可刪除紀錄。</p>
            </div>
            <Button variant="ghost" size="xs" onClick={() => setExpanded(false)}>收起</Button>
          </div>

          <div className="max-h-[24rem] space-y-2 overflow-y-auto p-3">
            {visible.map(task => {
              const isActive = ACTIVE_STATUSES.has(task.status)
              const pct = progress(task)
              return (
                <div key={task.id} className="space-y-2 rounded-xl border border-border bg-card/70 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{taskSource(task)}</p>
                      <p className="mt-0.5 text-xs text-muted-foreground">#{task.id} · {STATUS_LABEL[task.status]}</p>
                    </div>
                    <Badge variant={task.status === 'failed' ? 'destructive' : 'outline'} className="shrink-0 text-[11px]">
                      {task.processed}/{task.total}
                    </Badge>
                  </div>

                  {isActive && (
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{task.status === 'waiting_for_agent' ? '等待 Agent 連線' : task.status === 'pending' ? '等待開始' : '處理中'}</span>
                        <span className="font-mono">{pct}%</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )}

                  {task.error && !isActive && (
                    <p className="line-clamp-2 text-xs text-destructive">{task.error}</p>
                  )}

                  <div className="flex justify-end">
                    {isActive ? (
                      <Button variant="destructive" size="xs" disabled={busyTaskId === task.id} onClick={() => stopTask(task.id)}>
                        {busyTaskId === task.id ? '停止中…' : '停止'}
                      </Button>
                    ) : (
                      <Button variant="ghost" size="xs" disabled={busyTaskId === task.id}
                        className="text-destructive hover:text-destructive" onClick={() => deleteTask(task.id)}>
                        {busyTaskId === task.id ? '刪除中…' : '刪除'}
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {error && <p className="border-t border-border px-4 py-2 text-xs text-destructive">{error}</p>}
        </div>
      )}

      <button
        type="button"
        aria-live="polite"
        onClick={() => setExpanded(value => !value)}
        className={`relative flex min-h-11 items-center gap-2 rounded-full border bg-popover/95 px-4 py-2.5 text-sm font-medium shadow-xl backdrop-blur-xl transition hover:bg-accent ${
          active.length > 0 ? 'border-primary/40 ring-2 ring-primary/10' : 'border-border'
        }`}
      >
        <span className={`h-2.5 w-2.5 rounded-full ${active.length > 0 ? 'bg-primary animate-pulse' : 'bg-muted-foreground/40'}`} />
        <span>{collapsedSummary(active)}</span>
        {active.length === 1 && active[0].status === 'running' && (
          <span className="text-xs font-mono text-muted-foreground">{active[0].processed}/{active[0].total}</span>
        )}
        {active.length === 0 && <span className="text-xs text-muted-foreground">{Math.min(tasks.length, 50)}</span>}
        <span className="text-xs text-muted-foreground">{expanded ? '▼' : '▲'}</span>
      </button>
    </div>,
    document.body,
  )
}
