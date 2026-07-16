import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, Task } from '../api/client'
import DarkToggle from '../components/DarkToggle'
import { useDarkMode } from '../hooks/useDarkMode'
import { useAuth } from '../context/AuthContext'

interface LLMConfig {
  api_url: string
  api_key: string
  model: string
  prompt_template: string
  examples_mode: string
  examples_per_label: number
  has_api_key?: boolean
}

export default function ProjectSettingsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { isDark, toggle } = useDarkMode()
  const { user, logout } = useAuth()
  const pid = Number(projectId)

  const [config, setConfig] = useState<LLMConfig>({
    api_url: '', api_key: '', model: '', prompt_template: '', examples_mode: 'corrected_only', examples_per_label: 3,
  })
  const [models, setModels] = useState<string[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [tasks, setTasks] = useState<Task[]>([])
  const [runningTask, setRunningTask] = useState<Task | null>(null)
  const [startingTask, setStartingTask] = useState(false)
  const [taskTarget, setTaskTarget] = useState<'pending' | 'all'>('pending')
  const [taskError, setTaskError] = useState<string | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load config and tasks
  useEffect(() => {
    api.getLLMConfig(pid).then(setConfig).catch(() => {})
    loadTasks()
  }, [pid])

  const loadTasks = () => {
    api.listTasks(pid).then(ts => {
      setTasks(ts)
      const running = ts.find(t => t.status === 'running' || t.status === 'pending')
      setRunningTask(running || null)
    }).catch(() => {})
  }

  // Poll running task
  useEffect(() => {
    if (runningTask) {
      pollRef.current = setInterval(() => {
        api.getTask(pid, runningTask.id).then(t => {
          setRunningTask(t.status === 'running' || t.status === 'pending' ? t : null)
          if (t.status === 'done' || t.status === 'failed') {
            clearInterval(pollRef.current!)
            loadTasks()
          }
        })
      }, 2000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [runningTask?.id])

  const fetchModels = async () => {
    if (!config.api_url) return
    setLoadingModels(true)
    try {
      const ms = await api.listLLMModels(pid)
      setModels(ms)
    } catch { setModels([]) }
    finally { setLoadingModels(false) }
  }

  const handleSave = async () => {
    setSaving(true); setSaveMsg(null); setSaveError(null)
    try {
      await api.updateLLMConfig(pid, config)
      setSaveMsg('已儲存')
      setTimeout(() => setSaveMsg(null), 2000)
    } catch (e: any) { setSaveError(e.message) }
    finally { setSaving(false) }
  }

  const handleStartTask = async () => {
    setStartingTask(true); setTaskError(null)
    try {
      await api.updateLLMConfig(pid, config)
      const task = await api.createTask(pid, { target: taskTarget, slot: 1, execution_mode: 'api', executor_name: 'platform-api' })
      setRunningTask(task)
      loadTasks()
    } catch (e: any) { setTaskError(e.message) }
    finally { setStartingTask(false) }
  }

  const pct = runningTask && runningTask.total > 0
    ? Math.round((runningTask.processed / runningTask.total) * 100)
    : 0

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors">
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center gap-3">
          <button onClick={() => navigate(`/projects/${pid}`)} className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">← 返回專案</button>
          <span className="text-gray-300 dark:text-gray-600">/</span>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100 flex-1">LLM 設定與批次重新分類</h1>
          <DarkToggle isDark={isDark} toggle={toggle} />
          <span className="text-sm text-gray-500 dark:text-gray-400">{user?.username}</span>
          <button onClick={logout} className="px-3 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">登出</button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6 space-y-6">

        {/* LLM 連線設定 */}
        <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">LLM 連線設定</h2>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">API URL</label>
              <div className="flex gap-2">
                <input
                  type="text" value={config.api_url}
                  onChange={e => setConfig(c => ({ ...c, api_url: e.target.value }))}
                  placeholder="http://192.168.1.79:18123/v1"
                  className="flex-1 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button onClick={fetchModels} disabled={!config.api_url || loadingModels}
                  className="px-3 py-2 text-xs border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-40 transition-colors whitespace-nowrap">
                  {loadingModels ? '讀取…' : '取得模型'}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                API Key <span className="font-normal text-gray-400 dark:text-gray-500">（選填，OpenAI / 付費服務需要）</span>
              </label>
              <input
                type="password" value={config.api_key}
                onChange={e => setConfig(c => ({ ...c, api_key: e.target.value }))}
                placeholder="sk-..."
                className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              {config.has_api_key && (
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">🔒 已設定金鑰（僅顯示遮罩）；如需更換請直接輸入新的，清空則會移除</p>
              )}
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">模型</label>
              {models.length > 0 ? (
                <select value={config.model} onChange={e => setConfig(c => ({ ...c, model: e.target.value }))}
                  className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">選擇模型</option>
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : (
                <input type="text" value={config.model}
                  onChange={e => setConfig(c => ({ ...c, model: e.target.value }))}
                  placeholder="手動輸入模型 ID"
                  className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              )}
            </div>
          </div>
        </section>

        {/* Prompt 設定 */}
        <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Prompt 模板</h2>
            <p className="text-xs text-gray-400 dark:text-gray-500">使用 <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{'{examples}'}</code> 插入人工複查範例，<code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">{'{comment}'}</code> 插入待分類留言</p>
          </div>
          <textarea
            value={config.prompt_template}
            onChange={e => setConfig(c => ({ ...c, prompt_template: e.target.value }))}
            rows={12}
            className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </section>

        {/* Few-shot 例子設定 */}
        <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Few-shot 例子設定</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">例子來源</label>
              <div className="space-y-2">
                {[
                  { value: 'corrected_only', label: '只用有修改的', desc: '人工修正過的筆數（信號最強）' },
                  { value: 'all_reviewed', label: '全部已審查', desc: '包含核准和修正的筆數' },
                ].map(opt => (
                  <label key={opt.value} className="flex items-start gap-2 cursor-pointer">
                    <input type="radio" name="examples_mode" value={opt.value}
                      checked={config.examples_mode === opt.value}
                      onChange={() => setConfig(c => ({ ...c, examples_mode: opt.value }))}
                      className="mt-0.5 text-blue-600" />
                    <div>
                      <p className="text-sm text-gray-900 dark:text-gray-100">{opt.label}</p>
                      <p className="text-xs text-gray-400 dark:text-gray-500">{opt.desc}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">每種標籤最多幾筆例子</label>
              <input type="number" min={1} max={10} value={config.examples_per_label}
                onChange={e => setConfig(c => ({ ...c, examples_per_label: Number(e.target.value) }))}
                className="w-24 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">每種愛的語言標籤各取 N 筆作為範例，確保多樣性</p>
            </div>
          </div>
        </section>

        {/* 儲存設定 */}
        <div className="flex items-center gap-3">
          <button onClick={handleSave} disabled={saving}
            className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {saving ? '儲存中…' : '儲存設定'}
          </button>
          {saveMsg && <span className="text-sm text-green-600 dark:text-green-400">{saveMsg}</span>}
          {saveError && <span className="text-sm text-red-600 dark:text-red-400">{saveError}</span>}
        </div>

        {/* 批次重新分類 */}
        <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">批次重新分類</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">系統會用目前人工複查的結果作為 few-shot 例子，重新跑 LLM 分類。已核准的筆數不會被動到。</p>

          {runningTask ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-700 dark:text-gray-300 font-medium">分類中…</span>
                <span className="font-mono text-gray-500 dark:text-gray-400">{runningTask.processed} / {runningTask.total} ({pct}%)</span>
              </div>
              <div className="h-3 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500 transition-all duration-500 rounded-full" style={{ width: `${pct}%` }} />
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-end gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">分類目標</label>
                <div className="flex gap-4">
                  {[
                    { value: 'pending' as const, label: '只跑待審筆數' },
                    { value: 'all' as const, label: '待審 + 已修正' },
                  ].map(opt => (
                    <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                      <input type="radio" name="task_target" value={opt.value}
                        checked={taskTarget === opt.value}
                        onChange={() => setTaskTarget(opt.value)}
                        className="text-blue-600" />
                      <span className="text-sm text-gray-700 dark:text-gray-300">{opt.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <button onClick={handleStartTask} disabled={startingTask || !config.api_url || !config.model}
                className="px-5 py-2 bg-purple-600 text-white rounded-lg text-sm font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {startingTask ? '啟動中…' : '開始重新分類'}
              </button>
              {taskError && <p className="text-sm text-red-600 dark:text-red-400 w-full">{taskError}</p>}
            </div>
          )}
        </section>

        {/* 任務記錄 */}
        {tasks.length > 0 && (
          <section className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">任務記錄</h2>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                  <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400 text-xs">時間</th>
                  <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400 text-xs w-24">狀態</th>
                  <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400 text-xs w-32">進度</th>
                  <th className="text-left px-4 py-2 font-medium text-gray-600 dark:text-gray-400 text-xs">備註</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {tasks.map(t => {
                  const p = t.total > 0 ? Math.round((t.processed / t.total) * 100) : 0
                  const statusMap: Record<string, { label: string; cls: string }> = {
                    pending: { label: '等待中', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300' },
                    running: { label: '執行中', cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400' },
                    done:    { label: '完成',   cls: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' },
                    failed:  { label: '失敗',   cls: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' },
                  }
                  const s = statusMap[t.status] || statusMap.pending
                  return (
                    <tr key={t.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 font-mono text-xs">{t.created_at?.slice(0, 16).replace('T', ' ')}</td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${s.cls}`}>{s.label}</span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 text-xs">{t.processed} / {t.total} ({p}%)</td>
                      <td className="px-4 py-2.5 text-red-500 dark:text-red-400 text-xs">{t.error || ''}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </section>
        )}
      </main>
    </div>
  )
}
