import { useEffect, useMemo, useRef, useState } from 'react'
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

const EMPTY: SlotCfg = {
  name: '',
  api_url: '',
  api_key: '',
  model: '',
  prompt_template: '',
  examples_mode: 'corrected_only',
  examples_per_label: 3,
  concurrency: 1,
  extra_body: '',
  has_api_key: false,
}

const ACTIVE_STATUSES = new Set<Task['status']>(['pending', 'waiting_for_agent', 'running'])

const TASK_STATUS_LABEL: Record<Task['status'], string> = {
  pending: '等待中',
  waiting_for_agent: '等待 Agent',
  running: '執行中',
  done: '完成',
  failed: '失敗',
  cancelled: '已停止',
}

const TASK_STATUS_CLS: Record<Task['status'], string> = {
  pending: 'bg-muted text-muted-foreground',
  waiting_for_agent: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  running: 'bg-primary/10 text-primary',
  done: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  failed: 'bg-destructive/10 text-destructive',
  cancelled: 'bg-muted text-muted-foreground',
}

interface Props {
  projectId: number
  open: boolean
  onClose: () => void
  onTasksChanged?: () => void
}

function isConfigured(cfg: SlotCfg) {
  return Boolean(cfg.api_url && cfg.model)
}

function getMcpUrl(): string {
  const { protocol, hostname, port, origin } = window.location
  const isLocalHost = hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
  if (isLocalHost && protocol === 'http:' && port === '8080') return `https://${hostname}/mcp`
  return `${origin}/mcp`
}

function buildSetupCommand(agent: 'codex' | 'claude', token: string, url: string): string {
  const t = token || '貼上剛建立的權杖'
  if (agent === 'codex') {
    return `export ANNOTATION_MCP_TOKEN="${t}"\ncodex mcp add annotation-platform --url ${url} --bearer-token-env-var ANNOTATION_MCP_TOKEN`
  }
  return `export ANNOTATION_MCP_TOKEN="${t}"\nclaude mcp add --transport http annotation-platform ${url} --header "Authorization: Bearer \${ANNOTATION_MCP_TOKEN}"`
}

function taskSource(task: Task, slots: Record<number, SlotCfg>): string {
  if (task.execution_mode === 'mcp') {
    return task.executor_name === 'claude' ? 'Claude Code MCP' : 'Codex / ChatGPT MCP'
  }
  const cfg = task.slot ? slots[task.slot] : undefined
  return cfg?.name || task.executor_name || `平台模型 ${task.slot ?? ''}`.trim()
}

function SlotPanel({
  slot,
  cfg,
  setCfg,
  pid,
  onSave,
}: {
  slot: number
  cfg: SlotCfg
  setCfg: (updater: (prev: SlotCfg) => SlotCfg) => void
  pid: number
  onSave: () => Promise<void>
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
    try {
      await onSave()
      setModels(await api.listLLMModelsForSlot(pid, slot))
    } catch {
      setModels([])
    } finally {
      setLoadingModels(false)
    }
  }

  const handlePreview = async () => {
    setLoadingPreview(true)
    try {
      await onSave()
      setPreview(await api.previewPromptForSlot(pid, slot))
    } catch (e) {
      setPreview({ example_count: 0, prompt: `錯誤：${e instanceof Error ? e.message : String(e)}` })
    } finally {
      setLoadingPreview(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg(null)
    try {
      await onSave()
      setSaveMsg('已儲存')
      window.setTimeout(() => setSaveMsg(null), 1800)
    } catch (e) {
      setSaveMsg(`錯誤：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      <button
        type="button"
        onClick={() => setExpanded(value => !value)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50"
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${configured ? 'bg-emerald-500' : 'bg-muted-foreground/30'}`} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-foreground">{cfg.name || `LLM ${slot}`}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {configured ? cfg.model : '尚未設定 API URL / Model'}
          </span>
        </span>
        <Badge variant={configured ? 'secondary' : 'outline'} className="text-xs">
          {configured ? 'Ready' : '未設定'}
        </Badge>
        <span className="text-xs text-muted-foreground">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="space-y-5 border-t border-border px-4 pb-5 pt-4">
          <div className="space-y-1.5">
            <Label className="text-xs">顯示名稱</Label>
            <Input
              value={cfg.name}
              onChange={event => setCfg(current => ({ ...current, name: event.target.value }))}
              placeholder={`LLM ${slot}`}
              className="h-8 max-w-xs text-sm"
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label className="text-xs">API URL</Label>
              <div className="flex gap-1.5">
                <Input
                  value={cfg.api_url}
                  onChange={event => setCfg(current => ({ ...current, api_url: event.target.value }))}
                  placeholder="http://host:port/v1"
                  className="h-8 text-sm"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={fetchModels}
                  disabled={!cfg.api_url || loadingModels || Boolean(extraBodyError)}
                  className="shrink-0 text-xs"
                >
                  {loadingModels ? '…' : '取得模型'}
                </Button>
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">API Key <span className="font-normal text-muted-foreground">（選填）</span></Label>
              <Input
                type="password"
                value={cfg.api_key}
                onChange={event => setCfg(current => ({ ...current, api_key: event.target.value }))}
                placeholder="sk-..."
                className="h-8 text-sm"
              />
              {cfg.has_api_key && (
                <p className="text-xs text-muted-foreground">已存在一組 Key；輸入新值可替換。</p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">模型</Label>
              {models.length > 0 ? (
                <Select value={cfg.model} onValueChange={value => setCfg(current => ({ ...current, model: value ?? '' }))}>
                  <SelectTrigger className="h-8 text-sm"><SelectValue placeholder="選擇模型" /></SelectTrigger>
                  <SelectContent>
                    {models.map(model => <SelectItem key={model} value={model}>{model}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  value={cfg.model}
                  onChange={event => setCfg(current => ({ ...current, model: event.target.value }))}
                  placeholder="手動輸入模型 ID"
                  className="h-8 text-sm"
                />
              )}
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-[9rem_1fr]">
            <div className="space-y-1.5">
              <Label className="text-xs">並發數</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={cfg.concurrency}
                onChange={event => setCfg(current => ({
                  ...current,
                  concurrency: Math.max(1, Math.min(100, Number(event.target.value))),
                }))}
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">額外 Request Body <span className="font-normal text-muted-foreground">（JSON，選填）</span></Label>
              <textarea
                value={cfg.extra_body}
                onChange={event => setCfg(current => ({ ...current, extra_body: event.target.value }))}
                rows={3}
                placeholder='例如：{"chat_template_kwargs": {"enable_thinking": false}}'
                className={`w-full resize-y rounded-lg border bg-card px-3 py-2 font-mono text-xs text-foreground focus:outline-none focus:ring-2 ${
                  extraBodyError ? 'border-destructive focus:ring-destructive/30' : 'border-input focus:ring-ring/50'
                }`}
              />
              {extraBodyError && <p className="text-xs text-destructive">{extraBodyError}</p>}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label className="text-xs">共享 Prompt（所有模型 / MCP 共用）</Label>
              <span className="text-xs text-muted-foreground">
                可用 <code className="rounded bg-muted px-1">{'{examples}'}</code>{' '}
                <code className="rounded bg-muted px-1">{'{comment}'}</code>
              </span>
            </div>
            <textarea
              value={cfg.prompt_template}
              onChange={event => setCfg(current => ({ ...current, prompt_template: event.target.value }))}
              rows={7}
              placeholder="留空則使用系統預設 Prompt"
              className="w-full resize-y rounded-lg border border-input bg-card px-3 py-2 font-mono text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring/50"
            />
            <p className="text-xs text-muted-foreground">這是專案層級 Prompt。從任一模型修改並儲存後，其他模型與 MCP 會立即同步使用同一份 Prompt。</p>
          </div>

          <div className="flex flex-wrap gap-6 rounded-xl bg-muted/30 p-3">
            <div className="space-y-2">
              <Label className="text-xs">Few-shot 來源</Label>
              <RadioGroup
                value={cfg.examples_mode}
                onValueChange={value => setCfg(current => ({ ...current, examples_mode: value }))}
                className="gap-2"
              >
                <label className="flex cursor-pointer items-start gap-2" htmlFor={`mode-${slot}-corrected`}>
                  <RadioGroupItem id={`mode-${slot}-corrected`} value="corrected_only" className="mt-0.5" />
                  <span>
                    <span className="block text-sm">只用人工修正</span>
                    <span className="block text-xs text-muted-foreground">品質較高、數量較少。</span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-2" htmlFor={`mode-${slot}-reviewed`}>
                  <RadioGroupItem id={`mode-${slot}-reviewed`} value="all_reviewed" className="mt-0.5" />
                  <span>
                    <span className="block text-sm">全部已審查</span>
                    <span className="block text-xs text-muted-foreground">包含核准與人工修正。</span>
                  </span>
                </label>
              </RadioGroup>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">每種標籤最多幾筆</Label>
              <Input
                type="number"
                min={1}
                max={10}
                value={cfg.examples_per_label}
                onChange={event => setCfg(current => ({ ...current, examples_per_label: Number(event.target.value) }))}
                className="h-8 w-24 text-sm"
              />
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={handlePreview} disabled={loadingPreview || !cfg.api_url || Boolean(extraBodyError)}>
                {loadingPreview ? '產生中…' : '預覽 Prompt'}
              </Button>
              {preview && <Button variant="ghost" size="sm" onClick={() => setPreview(null)}>收起</Button>}
            </div>
            {preview && (
              <div className="space-y-1.5 rounded-lg border border-border bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">Few-shot：{preview.example_count} 筆</p>
                <pre className="max-h-52 overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-foreground">{preview.prompt}</pre>
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            <Button size="sm" onClick={handleSave} disabled={saving || Boolean(extraBodyError)}>
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

export default function LLMSettingsAdvancedModal({ projectId: pid, open, onClose, onTasksChanged }: Props) {
  const [slots, setSlots] = useState<Record<number, SlotCfg>>({ 1: EMPTY, 2: EMPTY, 3: EMPTY })
  const [tasks, setTasks] = useState<Task[]>([])
  const [apiTokens, setApiTokens] = useState<ApiToken[]>([])
  const [mcpConnections, setMcpConnections] = useState<McpOAuthConnection[]>([])
  const [newToken, setNewToken] = useState('')
  const [newTokenId, setNewTokenId] = useState<number | null>(null)
  const [tokenBusy, setTokenBusy] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [taskBusyId, setTaskBusyId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const activeTasks = useMemo(() => tasks.filter(task => ACTIVE_STATUSES.has(task.status)), [tasks])
  const mcpUrl = getMcpUrl()
  const codexCommand = buildSetupCommand('codex', newToken, mcpUrl)
  const claudeCommand = buildSetupCommand('claude', newToken, mcpUrl)

  const setCfg = (slot: number) => (updater: (prev: SlotCfg) => SlotCfg) => {
    setSlots(current => ({ ...current, [slot]: updater(current[slot] ?? EMPTY) }))
  }

  const saveCfg = async (slot: number) => {
    const cfg = slots[slot]
    if (cfg.api_url || cfg.model) {
      const saved = await api.setLLMConfig(pid, slot, { ...cfg, name: cfg.name || `LLM ${slot}` })
      setSlots(current => ({
        ...current,
        1: { ...(current[1] ?? EMPTY), prompt_template: saved.prompt_template },
        2: { ...(current[2] ?? EMPTY), prompt_template: saved.prompt_template },
        3: { ...(current[3] ?? EMPTY), prompt_template: saved.prompt_template },
      }))
    } else {
      await api.deleteLLMConfigSlot(pid, slot).catch(() => {})
    }
  }

  const refreshTasks = async () => {
    try {
      setTasks(await api.listTasks(pid))
      onTasksChanged?.()
    } catch {
      // Keep previous task history on a temporary polling failure.
    }
  }

  const loadSettings = async () => {
    const [configsResult, tokensResult, connectionsResult, tasksResult] = await Promise.allSettled([
      api.getLLMConfigs(pid),
      api.listApiTokens(),
      api.listMcpOAuthConnections(),
      api.listTasks(pid),
    ])

    if (configsResult.status === 'fulfilled') {
      const next: Record<number, SlotCfg> = { 1: EMPTY, 2: EMPTY, 3: EMPTY }
      configsResult.value.forEach(config => {
        next[config.slot] = {
          name: config.name,
          api_url: config.api_url,
          api_key: config.api_key,
          model: config.model,
          prompt_template: config.prompt_template,
          examples_mode: config.examples_mode,
          examples_per_label: config.examples_per_label,
          concurrency: config.concurrency ?? 1,
          extra_body: config.extra_body ?? '',
          has_api_key: config.has_api_key ?? false,
        }
      })
      setSlots(next)
    }

    if (tokensResult.status === 'fulfilled') setApiTokens(tokensResult.value)
    if (connectionsResult.status === 'fulfilled') setMcpConnections(connectionsResult.value)
    if (tasksResult.status === 'fulfilled') setTasks(tasksResult.value)
  }

  useEffect(() => {
    if (!open) return
    loadSettings()
  }, [open, pid])

  useEffect(() => {
    if (!open || activeTasks.length === 0) return
    pollRef.current = window.setInterval(refreshTasks, 2500)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [open, activeTasks.length, pid])

  const createAccessToken = async () => {
    setTokenBusy(true)
    setError(null)
    try {
      const token = await api.createApiToken('Codex / Claude MCP')
      setNewToken(token.token || '')
      setNewTokenId(token.id)
      setApiTokens(await api.listApiTokens())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTokenBusy(false)
    }
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const revokeMcpConnection = async (id: number) => {
    if (!window.confirm('確定撤銷這個 GUI MCP 連線？該 App 將立即無法繼續使用。')) return
    try {
      await api.revokeMcpOAuthConnection(id)
      setMcpConnections(await api.listMcpOAuthConnections())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const stopTask = async (taskId: number) => {
    if (!window.confirm('確定停止這個分類任務？')) return
    setTaskBusyId(taskId)
    setError(null)
    try {
      await api.cancelTask(pid, taskId)
      await refreshTasks()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTaskBusyId(null)
    }
  }

  const deleteTask = async (taskId: number) => {
    if (!window.confirm('確定刪除這筆任務紀錄？')) return
    setTaskBusyId(taskId)
    setError(null)
    try {
      await api.deleteTask(pid, taskId)
      await refreshTasks()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setTaskBusyId(null)
    }
  }

  const copyText = async (key: string, value: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = value
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(textarea)
        if (!ok) throw new Error('copy failed')
      }
      setCopied(key)
      window.setTimeout(() => setCopied(null), 1600)
    } catch {
      setError('自動複製失敗，請手動複製。')
    }
  }

  return (
    <Dialog open={open} onOpenChange={value => { if (!value) onClose() }}>
      <DialogContent className="sm:max-w-4xl h-[90vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="shrink-0 border-b px-6 py-4">
          <div className="pr-8">
            <DialogTitle>進階分類設定</DialogTitle>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              這裡管理模型連線、專案共用 Prompt、Few-shot、MCP 連線與完整任務紀錄。Codebook 與開始分類請回到自動分類主畫面操作。
            </p>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-7 overflow-y-auto px-6 py-5">
          <section className="space-y-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">平台 LLM</p>
              <p className="mt-1 text-sm text-muted-foreground">模型可有不同 Provider / Model，但分類 Prompt 與 Codebook 維持專案層級共用。</p>
            </div>
            {([1, 2, 3] as const).map(slot => (
              <SlotPanel
                key={slot}
                slot={slot}
                cfg={slots[slot]}
                setCfg={setCfg(slot)}
                pid={pid}
                onSave={() => saveCfg(slot)}
              />
            ))}
          </section>

          <Separator />

          <section className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Codex / Claude MCP</p>
              <p className="mt-1 text-sm text-muted-foreground">管理 GUI OAuth 連線與 CLI / Developer access token。</p>
            </div>

            <div className="space-y-4 rounded-2xl border border-violet-200 bg-violet-50/30 p-4 dark:border-violet-900 dark:bg-violet-950/10">
              <div className="space-y-2">
                <div>
                  <p className="text-sm font-medium">GUI App / OAuth</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">ChatGPT / Codex 類 GUI Client 使用 MCP URL 連線，首次連線會走 OAuth 授權。</p>
                </div>
                <div className="flex gap-2">
                  <Input readOnly value={mcpUrl} className="font-mono text-xs" />
                  <Button variant="outline" size="sm" onClick={() => copyText('mcp-url', mcpUrl)}>
                    {copied === 'mcp-url' ? '已複製' : '複製 URL'}
                  </Button>
                </div>
                {mcpConnections.length > 0 ? (
                  <div className="space-y-1.5 pt-1">
                    {mcpConnections.map(connection => (
                      <div key={connection.id} className="flex items-center justify-between gap-3 rounded-lg bg-card/80 px-3 py-2 text-xs">
                        <span className="min-w-0 truncate">
                          <span className="font-medium">{connection.client_name}</span>
                          <span className="ml-2 text-muted-foreground">{connection.scopes.replace(/offline_access/g, '維持連線')}</span>
                        </span>
                        <Button variant="ghost" size="xs" className="text-destructive" onClick={() => revokeMcpConnection(connection.id)}>撤銷</Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">目前沒有 GUI OAuth 連線。</p>
                )}
              </div>

              <Separator />

              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">CLI / Developer token</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">Codex CLI 或 Claude Code 可使用 access token。新權杖只顯示一次。</p>
                  </div>
                  <Button variant="outline" size="sm" onClick={createAccessToken} disabled={tokenBusy}>
                    {tokenBusy ? '建立中…' : '建立新權杖'}
                  </Button>
                </div>

                {newToken && (
                  <div className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/20">
                    <div>
                      <p className="text-sm font-medium">新權杖（只顯示這一次）</p>
                      <p className="text-xs text-muted-foreground">請立即保存。Codex 與 Claude Code 可以使用同一組權杖。</p>
                    </div>
                    <div className="flex gap-2">
                      <Input readOnly value={newToken} onFocus={event => event.currentTarget.select()} className="font-mono text-xs" />
                      <Button variant="outline" size="sm" onClick={() => copyText('token', newToken)}>
                        {copied === 'token' ? '已複製' : '複製 Token'}
                      </Button>
                    </div>
                    <div className="grid gap-2 lg:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs">Codex CLI</Label>
                        <textarea readOnly rows={4} value={codexCommand} className="w-full rounded-md border bg-card px-3 py-2 font-mono text-xs" />
                        <Button variant="outline" size="sm" onClick={() => copyText('codex-command', codexCommand)}>
                          {copied === 'codex-command' ? '已複製' : '複製 Codex 指令'}
                        </Button>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs">Claude Code</Label>
                        <textarea readOnly rows={4} value={claudeCommand} className="w-full rounded-md border bg-card px-3 py-2 font-mono text-xs" />
                        <Button variant="outline" size="sm" onClick={() => copyText('claude-command', claudeCommand)}>
                          {copied === 'claude-command' ? '已複製' : '複製 Claude 指令'}
                        </Button>
                      </div>
                    </div>
                  </div>
                )}

                {apiTokens.length > 0 && (
                  <div className="space-y-1.5">
                    {apiTokens.map(token => (
                      <div key={token.id} className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 px-3 py-2 text-xs">
                        <span className="min-w-0 truncate">
                          <span className="font-medium">{token.name}</span>
                          <span className="ml-2 font-mono text-muted-foreground">{token.token_prefix}…</span>
                        </span>
                        <Button variant="ghost" size="xs" className="text-destructive" onClick={() => revokeAccessToken(token.id)}>撤銷</Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          <Separator />

          <section className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">完整任務紀錄</p>
                <p className="mt-1 text-sm text-muted-foreground">最多顯示最近 50 筆。執行中的任務可停止；已結束的任務可刪除。</p>
              </div>
              {activeTasks.length > 0 && <Badge variant="secondary">{activeTasks.length} 個執行中</Badge>}
            </div>

            {tasks.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">尚無任務紀錄</div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-border">
                <table className="w-full min-w-[760px] text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">時間</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">狀態</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">來源</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">範圍</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">進度</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">備註</th>
                      <th className="w-20 px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {tasks.map(task => {
                      const isActive = ACTIVE_STATUSES.has(task.status)
                      const pct = task.total > 0 ? Math.round((task.processed / task.total) * 100) : 0
                      return (
                        <tr key={task.id} className="hover:bg-muted/30">
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-muted-foreground">
                            {(task.created_at || '').slice(0, 16).replace('T', ' ')}
                          </td>
                          <td className="px-3 py-2">
                            <span className={`rounded px-1.5 py-0.5 font-medium ${TASK_STATUS_CLS[task.status]}`}>{TASK_STATUS_LABEL[task.status]}</span>
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">{taskSource(task, slots)}</td>
                          <td className="px-3 py-2 text-muted-foreground">{task.target === 'all' ? '全部' : '待審'}</td>
                          <td className="whitespace-nowrap px-3 py-2 font-mono text-muted-foreground">{task.processed}/{task.total} · {pct}%</td>
                          <td className="max-w-[220px] truncate px-3 py-2 text-destructive">{task.error || ''}</td>
                          <td className="px-3 py-2 text-right">
                            {isActive ? (
                              <Button variant="destructive" size="xs" disabled={taskBusyId === task.id} onClick={() => stopTask(task.id)}>
                                {taskBusyId === task.id ? '停止中…' : '停止'}
                              </Button>
                            ) : (
                              <Button variant="ghost" size="xs" disabled={taskBusyId === task.id} className="text-destructive hover:text-destructive" onClick={() => deleteTask(task.id)}>
                                {taskBusyId === task.id ? '刪除中…' : '刪除'}
                              </Button>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {error && <p className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter className="shrink-0 border-t px-6 py-3">
          <Button variant="outline" onClick={onClose}>返回自動分類</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
