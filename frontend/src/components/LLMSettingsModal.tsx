import { useEffect, useRef, useState } from 'react'
import { api, ApiToken, LLMSlotConfig, McpOAuthConnection, Task } from '../api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'

type SlotCfg = Omit<LLMSlotConfig, 'slot'>
const EMPTY: SlotCfg = { name: '', api_url: '', api_key: '', model: '', prompt_template: '', examples_mode: 'corrected_only', examples_per_label: 3, concurrency: 1, extra_body: '', has_api_key: false }
function isConfigured(cfg: SlotCfg) { return !!(cfg.api_url && cfg.model) }
function buildSetupCommand(agent: 'codex' | 'claude', token: string, url: string): string {
  const t = token || '貼上剛建立的權杖'
  if (agent === 'codex') {
    return `export ANNOTATION_MCP_TOKEN="${t}"\ncodex mcp add annotation-platform --url ${url} --bearer-token-env-var ANNOTATION_MCP_TOKEN`
  }
  return `export ANNOTATION_MCP_TOKEN="${t}"\nclaude mcp add --transport http annotation-platform ${url} --header "Authorization: Bearer \${ANNOTATION_MCP_TOKEN}"`
}
function getMcpUrl(): string {
  const { protocol, hostname, port, origin } = window.location
  const isLocalHost = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
  // 8080 是網站後端的除錯入口，/mcp 並不存在；本機 MCP 一律經由 Caddy 的 443。
  if (isLocalHost && protocol === 'http:' && port === '8080') return `https://${hostname}/mcp`
  return `${origin}/mcp`
}
interface Props { projectId: number; open: boolean; onClose: () => void; onTasksChanged?: () => void }

function SlotPanel({ slot, cfg, setCfg, pid, onSave }: {
  slot: number; cfg: SlotCfg
  setCfg: (updater: (prev: SlotCfg) => SlotCfg) => void
  pid: number; onSave: () => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [preview, setPreview] = useState<{ example_count: number; prompt: string } | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const configured = isConfigured(cfg)
  let extraBodyError: string | null = null
  if (cfg.extra_body.trim()) {
    try {
      const parsed = JSON.parse(cfg.extra_body)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        extraBodyError = '必須是 JSON 物件（例如 {"key": "value"}）'
      }
    } catch {
      extraBodyError = 'JSON 格式錯誤'
    }
  }

  const fetchModels = async () => {
    if (!cfg.api_url) return
    setLoadingModels(true)
    try { await onSave(); setModels(await api.listLLMModelsForSlot(pid, slot)) }
    catch { setModels([]) } finally { setLoadingModels(false) }
  }

  const handlePreview = async () => {
    setLoadingPreview(true)
    try { await onSave(); setPreview(await api.previewPromptForSlot(pid, slot)) }
    catch (e: unknown) { setPreview({ example_count: 0, prompt: `錯誤：${e instanceof Error ? e.message : String(e)}` }) }
    finally { setLoadingPreview(false) }
  }

  const handleSave = async () => {
    setSaving(true); setSaveMsg(null)
    try { await onSave(); setSaveMsg('已儲存'); setTimeout(() => setSaveMsg(null), 2000) }
    catch (e: unknown) { setSaveMsg(`錯誤：${e instanceof Error ? e.message : String(e)}`) }
    finally { setSaving(false) }
  }

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-muted/50 transition-colors text-left">
        <span className={`w-2 h-2 rounded-full shrink-0 ${configured ? 'bg-emerald-500' : 'bg-muted-foreground/30'}`} />
        <span className="font-medium text-sm text-foreground flex-1">
          {cfg.name || `LLM ${slot}`}
          {configured && <span className="ml-2 text-xs text-muted-foreground font-normal">{cfg.model}</span>}
        </span>
        {!configured && <Badge variant="outline" className="text-xs">未設定</Badge>}
        <span className="text-muted-foreground text-xs">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-5 pt-4 border-t border-border space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs">名稱</Label>
            <Input value={cfg.name} onChange={e => setCfg(c => ({ ...c, name: e.target.value }))}
              placeholder={`LLM ${slot}`} className="w-48 h-8 text-sm" />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="sm:col-span-1 space-y-1.5">
              <Label className="text-xs">API URL</Label>
              <div className="flex gap-1.5">
                <Input value={cfg.api_url} onChange={e => setCfg(c => ({ ...c, api_url: e.target.value }))}
                  placeholder="http://host:port/v1" className="h-8 text-sm" />
                <Button variant="outline" size="sm" onClick={fetchModels}
                  disabled={!cfg.api_url || loadingModels || !!extraBodyError} className="shrink-0 text-xs">
                  {loadingModels ? '…' : '取得模型'}
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">API Key <span className="font-normal text-muted-foreground">（選填）</span></Label>
              <Input type="password" value={cfg.api_key} onChange={e => setCfg(c => ({ ...c, api_key: e.target.value }))}
                placeholder="sk-..." className="h-8 text-sm" />
              {cfg.has_api_key && (
                <p className="text-xs text-muted-foreground">🔒 已設定（僅顯示遮罩）；如需更換請直接輸入新的，清空則會移除</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">模型</Label>
              {models.length > 0 ? (
                <Select value={cfg.model} onValueChange={val => setCfg(c => ({ ...c, model: val ?? '' }))}>
                  <SelectTrigger className="h-8 text-sm"><SelectValue placeholder="選擇模型" /></SelectTrigger>
                  <SelectContent>{models.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              ) : (
                <Input value={cfg.model} onChange={e => setCfg(c => ({ ...c, model: e.target.value }))}
                  placeholder="手動輸入模型 ID" className="h-8 text-sm" />
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs">並發數</Label>
            <div className="flex items-center gap-3">
              <Input type="number" min={1} max={20} value={cfg.concurrency}
                onChange={e => setCfg(c => ({ ...c, concurrency: Math.max(1, Math.min(20, Number(e.target.value))) }))}
                className="w-20 h-8 text-sm" />
              <span className="text-xs text-muted-foreground">同時處理幾筆，建議 1–5</span>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-xs">Prompt 模板</Label>
              <span className="text-xs text-muted-foreground">
                <code className="bg-muted px-1 rounded">{'{examples}'}</code>
                <code className="bg-muted px-1 rounded ml-1">{'{comment}'}</code>
              </span>
            </div>
            <textarea value={cfg.prompt_template} onChange={e => setCfg(c => ({ ...c, prompt_template: e.target.value }))}
              rows={7} placeholder="留空則使用預設 Prompt"
              className="w-full border border-input bg-card text-foreground placeholder:text-muted-foreground rounded-lg px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-ring" />
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs">進階：額外請求參數（JSON，選填）</Label>
            <textarea value={cfg.extra_body} onChange={e => setCfg(c => ({ ...c, extra_body: e.target.value }))}
              rows={3} placeholder='例如關閉 thinking mode：{"chat_template_kwargs": {"enable_thinking": false}}'
              className={`w-full border bg-card text-foreground placeholder:text-muted-foreground rounded-lg px-3 py-2 text-xs font-mono resize-y focus:outline-none focus:ring-2 ${
                extraBodyError ? 'border-destructive focus:ring-destructive/30' : 'border-input focus:ring-ring/50 focus:border-ring'
              }`} />
            <p className={`text-xs ${extraBodyError ? 'text-destructive' : 'text-muted-foreground'}`}>
              {extraBodyError || '會直接合併進送給 LLM API 的 request body，依供應商格式而定'}
            </p>
          </div>

          <div className="flex flex-wrap gap-6">
            <div className="space-y-2">
              <Label className="text-xs">Few-shot 來源</Label>
              <RadioGroup value={cfg.examples_mode} onValueChange={val => setCfg(c => ({ ...c, examples_mode: val }))} className="gap-2">
                {[
                  { value: 'corrected_only', label: '只用有修改的', desc: '人工修正過的筆數' },
                  { value: 'all_reviewed',   label: '全部已審查',   desc: '包含核准和修正' },
                ].map(opt => (
                  <label key={opt.value} htmlFor={`mode_${slot}_${opt.value}`} className="flex items-start gap-2 cursor-pointer">
                    <RadioGroupItem value={opt.value} id={`mode_${slot}_${opt.value}`} className="mt-0.5" />
                    <div>
                      <span className="text-sm text-foreground">{opt.label}</span>
                      <p className="text-xs text-muted-foreground">{opt.desc}</p>
                    </div>
                  </label>
                ))}
              </RadioGroup>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">每種標籤最多幾筆</Label>
              <Input type="number" min={1} max={10} value={cfg.examples_per_label}
                onChange={e => setCfg(c => ({ ...c, examples_per_label: Number(e.target.value) }))}
                className="w-20 h-8 text-sm" />
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handlePreview} disabled={loadingPreview || !cfg.api_url || !!extraBodyError}>
                {loadingPreview ? '產生中…' : '預覽 Prompt'}
              </Button>
              {preview && <Button variant="ghost" size="sm" onClick={() => setPreview(null)}>收起</Button>}
            </div>
            {preview && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">
                  Few-shot：<span className={preview.example_count > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-500'}>
                    {preview.example_count > 0 ? `${preview.example_count} 筆` : '0 筆'}
                  </span>
                </p>
                <pre className="text-xs bg-muted border border-border rounded-lg p-3 overflow-auto max-h-48 text-foreground whitespace-pre-wrap font-mono leading-relaxed">
                  {preview.prompt}
                </pre>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3 pt-1">
            <Button onClick={handleSave} disabled={saving || !!extraBodyError} size="sm">
              {saving ? '儲存中…' : '儲存此 LLM'}
            </Button>
            {saveMsg && (
              <span className={`text-sm ${saveMsg.startsWith('錯誤') ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}`}>
                {saveMsg}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const TASK_STATUS_CLS: Record<string, string> = {
  pending: 'bg-muted text-muted-foreground',
  waiting_for_agent: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  running: 'bg-primary/10 text-primary',
  done:    'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  failed:  'bg-destructive/10 text-destructive',
  cancelled: 'bg-muted text-muted-foreground',
}
const TASK_STATUS_LABEL: Record<string, string> = {
  pending: '等待中', waiting_for_agent: '等待 Agent', running: '執行中', done: '完成', failed: '失敗', cancelled: '已取消',
}

function taskSource(t: Task) {
  if (t.execution_mode === 'mcp') return t.executor_name === 'claude' ? 'Claude Code MCP' : 'Codex MCP'
  return `平台 API · 槽 ${t.slot ?? 1}`
}

function SlotTaskHistory({ slotName, tasks, onCancel, onDelete }: {
  slotName: string; tasks: Task[]; pid: number; onCancel: (id: number) => void; onDelete: (id: number) => void
}) {
  const [open, setOpen] = useState(true)
  if (tasks.length === 0) return null
  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-muted/50 transition-colors text-left">
        <span className="text-xs font-medium text-muted-foreground flex-1">{slotName}</span>
        <span className="text-xs text-muted-foreground">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <table className="w-full text-xs border-t border-border">
          <thead>
            <tr className="bg-muted/50">
              <th className="text-left px-4 py-2 font-medium text-muted-foreground">時間</th>
              <th className="text-left px-4 py-2 font-medium text-muted-foreground w-16">狀態</th>
              <th className="text-left px-4 py-2 font-medium text-muted-foreground">執行來源</th>
              <th className="text-left px-4 py-2 font-medium text-muted-foreground w-24">進度</th>
              <th className="text-left px-4 py-2 font-medium text-muted-foreground">備註</th>
              <th className="w-14" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {tasks.map(t => {
              const p = t.total > 0 ? Math.round((t.processed / t.total) * 100) : 0
              return (
                <tr key={t.id} className="hover:bg-muted/30">
                  <td className="px-4 py-2 text-muted-foreground font-mono">{(t.created_at ?? '').slice(0, 16).replace('T', ' ')}</td>
                  <td className="px-4 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${TASK_STATUS_CLS[t.status] ?? TASK_STATUS_CLS.pending}`}>
                      {TASK_STATUS_LABEL[t.status] ?? '等待中'}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{taskSource(t)}</td>
                  <td className="px-4 py-2 text-muted-foreground">{t.processed}/{t.total} ({p}%)</td>
                  <td className="px-4 py-2 text-destructive truncate max-w-[160px]">{t.error || ''}</td>
                  <td className="px-2 py-2">
                    {(t.status === 'running' || t.status === 'pending' || t.status === 'waiting_for_agent') ? (
                      <Button variant="destructive" size="xs" onClick={() => onCancel(t.id)}>停止</Button>
                    ) : (
                      <Button variant="ghost" size="xs" onClick={() => onDelete(t.id)}
                        className="text-muted-foreground hover:text-destructive">刪除</Button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function LLMSettingsModal({ projectId: pid, open, onClose, onTasksChanged }: Props) {
  const [slots, setSlots] = useState<Record<number, SlotCfg>>({ 1: EMPTY, 2: EMPTY, 3: EMPTY })
  const [annotationInstructions, setAnnotationInstructions] = useState('')
  const [savedAnnotationInstructions, setSavedAnnotationInstructions] = useState('')
  const [correctedExamples, setCorrectedExamples] = useState(0)
  const [savingInstructions, setSavingInstructions] = useState(false)
  const [instructionsMessage, setInstructionsMessage] = useState<string | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [runningBySlot, setRunningBySlot] = useState<Record<number, Task | null>>({})
  const [selectedSlots, setSelectedSlots] = useState<number[]>([1, 2, 3])
  const [taskTarget, setTaskTarget] = useState<'pending' | 'all'>('pending')
  const [startingSlots, setStartingSlots] = useState<number[]>([])
  const [taskError, setTaskError] = useState<string | null>(null)
  const [executionMode, setExecutionMode] = useState<'api' | 'mcp'>('api')
  const [mcpAgent, setMcpAgent] = useState<'codex' | 'claude'>('codex')
  const [mcpSlot, setMcpSlot] = useState(1)
  const [createdMcpTask, setCreatedMcpTask] = useState<Task | null>(null)
  const [apiTokens, setApiTokens] = useState<ApiToken[]>([])
  const [mcpConnections, setMcpConnections] = useState<McpOAuthConnection[]>([])
  const [newToken, setNewToken] = useState('')
  const [newTokenId, setNewTokenId] = useState<number | null>(null)
  const [tokenBusy, setTokenBusy] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const setCfg = (slot: number) => (updater: (prev: SlotCfg) => SlotCfg) =>
    setSlots(s => ({ ...s, [slot]: updater(s[slot] ?? EMPTY) }))

  const saveCfg = async (slot: number) => {
    const cfg = slots[slot]
    if (cfg.api_url || cfg.model) {
      await api.setLLMConfig(pid, slot, { ...cfg, name: cfg.name || `LLM ${slot}` })
    } else {
      await api.deleteLLMConfigSlot(pid, slot).catch(() => {})
    }
  }

  const loadTasks = () => {
    api.listTasks(pid).then(ts => {
      setTasks(ts)
      const running: Record<number, Task | null> = {}
      ts.forEach(t => {
        if ((t.status === 'running' || t.status === 'pending' || t.status === 'waiting_for_agent') && t.slot != null) running[t.slot] = t
      })
      setRunningBySlot(running)
      onTasksChanged?.()
    }).catch(() => {})
  }

  useEffect(() => {
    if (!open) return
    api.getLLMConfigs(pid).then(cfgs => {
      const next: Record<number, SlotCfg> = { 1: EMPTY, 2: EMPTY, 3: EMPTY }
      cfgs.forEach(c => { next[c.slot] = { name: c.name, api_url: c.api_url, api_key: c.api_key, model: c.model, prompt_template: c.prompt_template, examples_mode: c.examples_mode, examples_per_label: c.examples_per_label, concurrency: c.concurrency ?? 1, extra_body: c.extra_body ?? '', has_api_key: c.has_api_key ?? false } })
      setSlots(next)
    }).catch(() => {})
    api.getProject(pid).then(project => {
      const instructions = project.annotation_instructions || ''
      setAnnotationInstructions(instructions)
      setSavedAnnotationInstructions(instructions)
      setCorrectedExamples(project.corrected || 0)
    }).catch(() => {})
    loadTasks()
    api.listApiTokens().then(setApiTokens).catch(() => {})
    api.listMcpOAuthConnections().then(setMcpConnections).catch(() => {})
  }, [open, pid])

  useEffect(() => {
    if (!open) { clearInterval(pollRef.current!); return }
    const hasRunning = Object.values(runningBySlot).some(t => t !== null)
    if (!hasRunning) return
    pollRef.current = setInterval(() => {
      Object.entries(runningBySlot).forEach(([slotStr, task]) => {
        if (!task) return
        api.getTask(pid, task.id).then(t => {
          setTasks(prev => prev.map(x => x.id === t.id ? t : x))
          if (t.status !== 'running' && t.status !== 'pending' && t.status !== 'waiting_for_agent') setRunningBySlot(prev => ({ ...prev, [Number(slotStr)]: null }))
          else setRunningBySlot(prev => ({ ...prev, [Number(slotStr)]: t }))
        })
      })
    }, 2000)
    return () => clearInterval(pollRef.current!)
  }, [open, JSON.stringify(runningBySlot)])

  const handleStartTask = async () => {
    const toRun = selectedSlots.filter(s => isConfigured(slots[s]) && !runningBySlot[s])
    if (toRun.length === 0) return
    setStartingSlots(toRun); setTaskError(null)
    try {
      if (annotationInstructions !== savedAnnotationInstructions) await saveInstructions()
      for (const slot of toRun) {
        await saveCfg(slot)
        await api.createTask(pid, {
          target: taskTarget, slot, execution_mode: 'api', executor_name: slots[slot].name || `LLM ${slot}`,
        })
      }
      loadTasks()
    } catch (e: unknown) { setTaskError(e instanceof Error ? e.message : String(e)) }
    finally { setStartingSlots([]) }
  }

  const handleStartMcpTask = async () => {
    setStartingSlots([mcpSlot]); setTaskError(null); setCreatedMcpTask(null)
    try {
      if (annotationInstructions !== savedAnnotationInstructions) await saveInstructions()
      const task = await api.createTask(pid, {
        target: taskTarget, slot: mcpSlot, execution_mode: 'mcp', executor_name: mcpAgent,
      })
      setCreatedMcpTask(task)
      loadTasks()
    } catch (e: unknown) { setTaskError(e instanceof Error ? e.message : String(e)) }
    finally { setStartingSlots([]) }
  }

  const saveInstructions = async () => {
    setSavingInstructions(true); setInstructionsMessage(null)
    try {
      const result = await api.updateAnnotationInstructions(pid, annotationInstructions)
      setAnnotationInstructions(result.annotation_instructions)
      setSavedAnnotationInstructions(result.annotation_instructions)
      setInstructionsMessage('Codebook 已儲存；下一個任務會使用最新版。')
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e)
      setInstructionsMessage(`儲存失敗：${message}`)
      throw e
    } finally { setSavingInstructions(false) }
  }

  const createAccessToken = async () => {
    setTokenBusy(true); setTaskError(null)
    try {
      const token = await api.createApiToken(`${mcpAgent === 'codex' ? 'Codex' : 'Claude Code'} MCP`)
      setNewToken(token.token || '')
      setNewTokenId(token.id)
      setApiTokens(await api.listApiTokens())
    } catch (e: unknown) { setTaskError(e instanceof Error ? e.message : String(e)) }
    finally { setTokenBusy(false) }
  }

  const revokeAccessToken = async (id: number) => {
    if (!window.confirm('確定撤銷這個 MCP 存取權杖？已連線的 Agent 將無法再使用。')) return
    try {
      await api.revokeApiToken(id)
      if (id === newTokenId) {
        setNewToken('')
        setNewTokenId(null)
      }
      setApiTokens(await api.listApiTokens())
    } catch (e: unknown) { setTaskError(e instanceof Error ? e.message : String(e)) }
  }

  const revokeMcpConnection = async (id: number) => {
    if (!window.confirm('確定撤銷這個 GUI MCP 連線？該 Codex／ChatGPT App 將立即無法繼續使用。')) return
    try {
      await api.revokeMcpOAuthConnection(id)
      setMcpConnections(await api.listMcpOAuthConnections())
    } catch (e: unknown) { setTaskError(e instanceof Error ? e.message : String(e)) }
  }

  const copyText = async (key: string, value: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value)
      } else {
        // navigator.clipboard 需要安全環境（HTTPS 或 localhost）；
        // 用 IP／純 HTTP 存取時該 API 不存在，改用舊式 execCommand 相容寫法。
        const ta = document.createElement('textarea')
        ta.value = value
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.focus()
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        if (!ok) throw new Error('execCommand copy failed')
      }
      setCopied(key)
      setTimeout(() => setCopied(null), 1800)
    } catch {
      alert('自動複製失敗（瀏覽器限制），請手動選取文字後用 Ctrl/Cmd+C 複製。')
    }
  }

  const handleCancel = async (taskId: number) => {
    if (!window.confirm('確定要強制停止這個任務？')) return
    try { await api.cancelTask(pid, taskId); loadTasks() }
    catch (e: unknown) { alert(e instanceof Error ? e.message : String(e)) }
  }

  const handleDelete = async (taskId: number) => {
    try { await api.deleteTask(pid, taskId); loadTasks() }
    catch (e: unknown) { alert(e instanceof Error ? e.message : String(e)) }
  }

  const tasksBySlot = (slot: number) => tasks.filter(t => t.slot === slot).slice(0, 10)
  const configuredSlots = ([1, 2, 3] as const).filter(s => isConfigured(slots[s]))
  const anyRunning = Object.values(runningBySlot).some(t => t !== null)
  const mcpUrl = getMcpUrl()
  const agentLabel = mcpAgent === 'codex' ? 'Codex' : 'Claude Code'
  const runInstruction = createdMcpTask
    ? `請執行標注平台 project ${pid} 的分類任務 #${createdMcpTask.id}。先 claim_labeling_task，接著反覆取得並提交批次，直到任務完成。`
    : ''
  const codexCommand = buildSetupCommand('codex', newToken, mcpUrl)
  const claudeCommand = buildSetupCommand('claude', newToken, mcpUrl)

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="sm:max-w-3xl h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="px-6 py-4 border-b shrink-0">
          <DialogTitle>LLM 設定</DialogTitle>
        </DialogHeader>

        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-6">
          <section className="rounded-xl border border-teal-200 dark:border-teal-900 bg-teal-50/40 dark:bg-teal-950/10 p-4 space-y-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-teal-700 dark:text-teal-300">專案 Codebook／Agent 指示</p>
              <p className="text-sm text-muted-foreground mt-1">
                這是此專案目前生效的完整規則。直接修改並儲存後，所有平台 API 與 MCP 任務都會使用此版本，以及精選的人工作答案例。
                目前可作為 few-shot 的已修正案例：{correctedExamples} 筆。
              </p>
            </div>
            <textarea value={annotationInstructions} onChange={e => setAnnotationInstructions(e.target.value)}
              rows={18} maxLength={12000}
              aria-label="專案 Codebook 完整規則"
              className="w-full border border-input bg-card text-foreground placeholder:text-muted-foreground rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-500" />
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">{annotationInstructions.length.toLocaleString()} / 12,000 字元</p>
              <Button variant="outline" size="sm" onClick={saveInstructions} disabled={savingInstructions || annotationInstructions === savedAnnotationInstructions}>
                {savingInstructions ? '儲存中…' : '儲存 Codebook'}
              </Button>
            </div>
            {instructionsMessage && <p className={`text-xs ${instructionsMessage.startsWith('儲存失敗') ? 'text-destructive' : 'text-emerald-600 dark:text-emerald-400'}`}>{instructionsMessage}</p>}
          </section>

          <Separator />

          <section className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">LLM 設定</p>
            {([1, 2, 3] as const).map(slot => (
              <SlotPanel key={slot} slot={slot} cfg={slots[slot]} setCfg={setCfg(slot)} pid={pid} onSave={() => saveCfg(slot)} />
            ))}
          </section>

          <Separator />

          <section className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">建立分類任務</p>
              <p className="text-sm text-muted-foreground mt-1">平台 API 可在背景自動完成；MCP 可使用你自己的 Codex 或 Claude Code。</p>
            </div>

            {anyRunning && (
              <div className="space-y-3">
                {([1, 2, 3] as const).map(slot => {
                  const task = runningBySlot[slot]
                  if (!task) return null
                  const pct = task.total > 0 ? Math.round((task.processed / task.total) * 100) : 0
                  return (
                    <div key={slot} className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-medium text-foreground">
                          {taskSource(task)} · {task.status === 'waiting_for_agent' ? '等待 Agent 連線' : '分類中…'}
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-muted-foreground">{task.processed}/{task.total} ({pct}%)</span>
                          <Button variant="destructive" size="xs" onClick={() => handleCancel(task.id)}>停止</Button>
                        </div>
                      </div>
                      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                        <div className="h-full bg-primary transition-all duration-500 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            <div className="grid sm:grid-cols-2 gap-3">
              <button type="button" onClick={() => setExecutionMode('api')}
                className={`rounded-xl border p-4 text-left transition-colors ${executionMode === 'api' ? 'border-primary bg-primary/5 ring-1 ring-primary/20' : 'border-border hover:bg-muted/40'}`}>
                <div className="flex items-center justify-between"><span className="font-medium text-sm">平台模型 API</span><Badge variant="secondary">推薦</Badge></div>
                <p className="text-xs text-muted-foreground mt-1">由平台背景執行，關閉頁面後仍會繼續。</p>
              </button>
              <button type="button" onClick={() => setExecutionMode('mcp')}
                className={`rounded-xl border p-4 text-left transition-colors ${executionMode === 'mcp' ? 'border-violet-500 bg-violet-500/5 ring-1 ring-violet-500/20' : 'border-border hover:bg-muted/40'}`}>
                <div className="flex items-center justify-between"><span className="font-medium text-sm">我的 Codex／Claude Code</span><Badge variant="outline">MCP</Badge></div>
                <p className="text-xs text-muted-foreground mt-1">使用自己的 Agent 用量，可中斷後繼續。</p>
              </button>
            </div>

            <div className="space-y-2">
              <Label className="text-xs">分類目標</Label>
              <RadioGroup value={taskTarget} onValueChange={val => setTaskTarget(val as 'pending' | 'all')} className="flex gap-4">
                {[{ value: 'pending', label: '只跑待審' }, { value: 'all', label: '待審+已修正' }].map(opt => (
                  <label key={opt.value} htmlFor={`target_${opt.value}`} className="flex items-center gap-1.5 cursor-pointer">
                    <RadioGroupItem value={opt.value} id={`target_${opt.value}`} />
                    <span className="text-sm text-foreground">{opt.label}</span>
                  </label>
                ))}
              </RadioGroup>
            </div>

            {executionMode === 'api' ? (
              <div className="rounded-xl border border-border p-4 space-y-4">
                <div className="space-y-2">
                  <Label className="text-xs">選擇要跑的平台模型</Label>
                  <div className="flex flex-wrap gap-4">
                    {([1, 2, 3] as const).map(slot => {
                      if (!isConfigured(slots[slot])) return null
                      const checked = selectedSlots.includes(slot)
                      const running = !!runningBySlot[slot]
                      return (
                        <label key={slot} className="flex items-center gap-1.5 cursor-pointer">
                          <input type="checkbox" checked={checked} disabled={running}
                            onChange={() => setSelectedSlots(prev => checked ? prev.filter(s => s !== slot) : [...prev, slot])}
                            className="rounded" />
                          <span className={`text-sm ${running ? 'text-muted-foreground' : 'text-foreground'}`}>
                            {slots[slot].name || `LLM ${slot}`}{running && '（使用中）'}
                          </span>
                        </label>
                      )
                    })}
                    {configuredSlots.length === 0 && <span className="text-xs text-muted-foreground">請先在上方設定至少一組 LLM API。</span>}
                  </div>
                </div>
                <Button onClick={handleStartTask}
                  disabled={startingSlots.length > 0 || selectedSlots.filter(s => isConfigured(slots[s]) && !runningBySlot[s]).length === 0}>
                  {startingSlots.length > 0 ? '啟動中…' : '開始背景分類'}
                </Button>
              </div>
            ) : (
              <div className="rounded-xl border border-violet-200 dark:border-violet-900 p-4 space-y-4 bg-violet-50/40 dark:bg-violet-950/10">
                <div className="grid sm:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label className="text-xs">Agent</Label>
                    <Select value={mcpAgent} onValueChange={v => setMcpAgent((v || 'codex') as 'codex' | 'claude')}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="codex">Codex</SelectItem><SelectItem value="claude">Claude Code</SelectItem></SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs">結果寫入槽位</Label>
                    <Select value={String(mcpSlot)} onValueChange={v => setMcpSlot(Number(v || 1))}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>{[1, 2, 3].map(slot => <SelectItem key={slot} value={String(slot)}>LLM 槽 {slot}{runningBySlot[slot] ? '（使用中）' : ''}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="rounded-lg bg-card border border-border p-3 space-y-3">
                  <div className="rounded-lg border border-violet-200 dark:border-violet-900 bg-violet-50/50 dark:bg-violet-950/20 p-3 space-y-2">
                    <div><p className="text-sm font-medium">Codex／ChatGPT GUI App</p><p className="text-xs text-muted-foreground mt-0.5">推薦方式：在 Workspace Developer Mode 建立 Custom MCP App，填入下方 MCP URL。首次 Connect 會開啟平台登入與授權頁，不需要建立或複製權杖。</p></div>
                    <div className="space-y-1"><Label className="text-xs">MCP URL</Label><div className="flex gap-2"><Input readOnly value={mcpUrl} className="font-mono text-xs" /><Button size="sm" variant="outline" onClick={() => copyText('oauth-url', mcpUrl)}>{copied === 'oauth-url' ? '已複製' : '複製'}</Button></div></div>
                    {mcpConnections.length > 0 && <div className="space-y-1 pt-1"><p className="text-xs font-medium">已連線的 GUI Apps</p>{mcpConnections.map(connection => <div key={connection.id} className="flex items-center justify-between gap-3 rounded-md bg-card/80 px-2.5 py-1.5 text-xs"><span className="min-w-0 truncate"><span className="font-medium">{connection.client_name}</span><span className="ml-2 text-muted-foreground">{connection.scopes.replace(/offline_access/g, '維持連線')}</span></span><Button variant="ghost" size="xs" className="text-destructive" onClick={() => revokeMcpConnection(connection.id)}>撤銷</Button></div>)}</div>}
                  </div>
                  <Separator />
                  <div className="flex items-center justify-between gap-3">
                    <div><p className="text-sm font-medium">CLI／Developer access token</p><p className="text-xs text-muted-foreground">進階／舊版 client fallback。有效權杖：{apiTokens.length} 個；新權杖只顯示一次。</p></div>
                    <Button variant="outline" size="sm" onClick={createAccessToken} disabled={tokenBusy}>{tokenBusy ? '建立中…' : `建立 ${agentLabel} 權杖`}</Button>
                  </div>
                  {newToken && (
                    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 space-y-3 dark:border-amber-900 dark:bg-amber-950/20">
                      <div>
                        <p className="text-sm font-medium">新權杖（只顯示這一次）</p>
                        <p className="text-xs text-muted-foreground">同一組權杖可設定 Codex 與 Claude Code；請立即複製保存。</p>
                      </div>
                      <div className="flex gap-2">
                        <Input readOnly value={newToken} onFocus={e => e.currentTarget.select()} className="font-mono text-xs" />
                        <Button size="sm" variant="outline" onClick={() => copyText('token', newToken)}>{copied === 'token' ? 'Token 已複製' : '複製 Token'}</Button>
                      </div>
                      <div className="space-y-2">
                        <div className="flex gap-2">
                          <textarea readOnly value={codexCommand} onFocus={e => e.currentTarget.select()} rows={3}
                            className="min-w-0 flex-1 rounded-md border bg-card px-3 py-2 font-mono text-xs" />
                          <Button size="sm" variant="outline" onClick={() => copyText('setup-codex', codexCommand)}>
                            {copied === 'setup-codex' ? '已複製' : '複製 Codex 指令'}
                          </Button>
                        </div>
                        <div className="flex gap-2">
                          <textarea readOnly value={claudeCommand} onFocus={e => e.currentTarget.select()} rows={3}
                            className="min-w-0 flex-1 rounded-md border bg-card px-3 py-2 font-mono text-xs" />
                          <Button size="sm" variant="outline" onClick={() => copyText('setup-claude', claudeCommand)}>
                            {copied === 'setup-claude' ? '已複製' : '複製 Claude 指令'}
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}
                  {!newToken && apiTokens.length > 0 && (
                    <p className="text-xs text-muted-foreground">既有權杖基於安全性無法再次顯示明文；若當時沒有保存，請建立一組新權杖。</p>
                  )}
                  {apiTokens.length > 0 && (
                    <div className="space-y-1">
                      {apiTokens.slice(0, 4).map(token => (
                        <div key={token.id} className="flex items-center justify-between gap-3 rounded-md bg-muted/50 px-2.5 py-1.5 text-xs">
                          <span className="truncate"><span className="font-medium">{token.name}</span> <span className="font-mono text-muted-foreground">{token.token_prefix}…</span></span>
                          <Button variant="ghost" size="xs" className="text-destructive" onClick={() => revokeAccessToken(token.id)}>撤銷</Button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="space-y-1"><Label className="text-xs">MCP URL</Label><div className="flex gap-2"><Input readOnly value={mcpUrl} className="font-mono text-xs" /><Button size="sm" variant="outline" onClick={() => copyText('url', mcpUrl)}>{copied === 'url' ? '已複製' : '複製'}</Button></div></div>
                </div>

                <Button onClick={handleStartMcpTask} disabled={startingSlots.length > 0 || !!runningBySlot[mcpSlot]}>
                  {startingSlots.length > 0 ? '建立中…' : `建立 ${agentLabel} 分類任務`}
                </Button>

                {createdMcpTask && (
                  <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-900 p-3 space-y-2">
                    <div className="flex items-center justify-between"><p className="text-sm font-medium">任務 #{createdMcpTask.id} 已建立</p><Badge className={TASK_STATUS_CLS.waiting_for_agent}>等待 Agent</Badge></div>
                    <p className="text-xs text-muted-foreground">連接 MCP 後，將以下指令貼給 {agentLabel}：</p>
                    <div className="flex gap-2"><textarea readOnly value={runInstruction} rows={3} className="flex-1 rounded-md border bg-card px-3 py-2 text-xs" /><Button variant="outline" size="sm" onClick={() => copyText('run', runInstruction)}>{copied === 'run' ? '已複製' : '複製'}</Button></div>
                  </div>
                )}
              </div>
            )}

            {taskError && <p className="text-sm text-destructive">{taskError}</p>}
          </section>

          {tasks.length > 0 && (
            <>
              <Separator />
              <section className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">任務紀錄</p>
                {([1, 2, 3] as const).map(slot => (
                  <SlotTaskHistory key={slot} slotName={slots[slot].name || `LLM ${slot}`}
                    tasks={tasksBySlot(slot)} pid={pid} onCancel={handleCancel} onDelete={handleDelete} />
                ))}
              </section>
            </>
          )}
        </div>

        <DialogFooter className="px-6 py-3 border-t shrink-0">
          <Button variant="outline" onClick={onClose}>關閉</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
