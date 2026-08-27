import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, RowDetail, Adjacent, AuditEntry } from '../api/client'
import {
  AnnotationResult,
  AnnotationSchema,
  GenericRowFields,
  coerceAnnotationResult,
  getProjectSchema,
  updateGenericRow,
} from '../api/annotation'
import {
  AnnotationFields,
  LLMComparison,
  resultFromRow,
  validateAnnotationSelection,
} from '../components/AnnotationControls'
import { useAuth } from '../context/AuthContext'
import HeaderUserMenu from '../components/HeaderUserMenu'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'

type GenericRowDetail = RowDetail & GenericRowFields

const EMPTY_RESULT: AnnotationResult = {
  relevance: null,
  labels: [],
  reason: '',
  metadata: {},
}

export default function ReviewPage() {
  const { projectId, rowId } = useParams<{ projectId: string; rowId: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const pid = Number(projectId)
  const rid = Number(rowId)

  const filterParams = {
    status: searchParams.get('status') || 'all',
    relevance: searchParams.get('relevance') || 'all',
    disagreement: searchParams.get('disagreement') || 'all',
    q: searchParams.get('q') || '',
    page: searchParams.get('page') || '1',
  }

  const queryClient = useQueryClient()
  const [row, setRow] = useState<GenericRowDetail | null>(null)
  const [schema, setSchema] = useState<AnnotationSchema | null>(null)
  const [result, setResult] = useState<AnnotationResult>(EMPTY_RESULT)
  const [adj, setAdj] = useState<Adjacent | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedOk, setSavedOk] = useState(false)
  const { user } = useAuth()
  const versionRef = useRef<number>(0)
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([])
  const [conflictWarning, setConflictWarning] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)

  const adjTotalCacheRef = useRef<{ sig: string; total: number } | null>(null)
  const [undoData, setUndoData] = useState<{
    rowId: number
    rowNum: number
    prevStatus: string
    savedStatus: 'approved' | 'uncertain'
  } | null>(null)
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const invalidateListCaches = useCallback(() => {
    adjTotalCacheRef.current = null
    queryClient.invalidateQueries({ queryKey: ['rows', pid] })
    queryClient.invalidateQueries({ queryKey: ['project', pid] })
  }, [pid, queryClient])

  const { data: presence = [] } = useQuery({
    queryKey: ['presence', pid],
    queryFn: () => api.getPresence(pid),
    refetchInterval: 5000,
  })

  const applyRowToForm = useCallback((nextRow: GenericRowDetail, activeSchema: AnnotationSchema) => {
    setRow(nextRow)
    versionRef.current = nextRow.version ?? 0
    setResult(resultFromRow(nextRow, activeSchema))
    setNote(nextRow.reviewer_note || '')
  }, [])

  const loadRow = useCallback(async (id: number) => {
    setLoading(true)
    setSaveError(null)
    const adjFilterSig = `${filterParams.status}|${filterParams.relevance}|${filterParams.q}`
    try {
      const [activeSchema, loadedRow, loadedAdj, audit] = await Promise.all([
        queryClient.fetchQuery({
          queryKey: ['annotation-schema', pid],
          queryFn: () => getProjectSchema(pid),
          staleTime: 60_000,
        }),
        queryClient.fetchQuery({
          queryKey: ['row', pid, id],
          queryFn: () => api.getRow(pid, id) as Promise<GenericRowDetail>,
          staleTime: 15_000,
        }),
        queryClient.fetchQuery({
          queryKey: ['adjacent', pid, id, filterParams.status, filterParams.relevance, filterParams.q],
          queryFn: async () => {
            const needsTotal = adjTotalCacheRef.current?.sig !== adjFilterSig
            const res = await api.getAdjacent(pid, id, { ...filterParams, include_total: needsTotal })
            if (res.total !== null) adjTotalCacheRef.current = { sig: adjFilterSig, total: res.total }
            return { ...res, total: res.total ?? adjTotalCacheRef.current?.total ?? 0 }
          },
          staleTime: 15_000,
        }),
        queryClient.fetchQuery({
          queryKey: ['audit', pid, id],
          queryFn: () => api.getAuditLog(pid, id),
          staleTime: 15_000,
        }),
      ])
      setSchema(activeSchema)
      setAdj(loadedAdj)
      setAuditLog(audit)
      setConflictWarning(null)
      applyRowToForm(loadedRow, activeSchema)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '載入失敗，請重試')
    } finally {
      setLoading(false)
    }
  }, [
    pid,
    filterParams.status,
    filterParams.relevance,
    filterParams.q,
    queryClient,
    applyRowToForm,
  ])

  useEffect(() => { loadRow(rid) }, [rid, loadRow])

  const goNext = useCallback(() => {
    if (adj?.next_id) navigate(`/projects/${pid}/review/${adj.next_id}?${new URLSearchParams(filterParams).toString()}`)
  }, [adj, pid, navigate, filterParams])

  const goPrev = useCallback(() => {
    if (adj?.prev_id) navigate(`/projects/${pid}/review/${adj.prev_id}?${new URLSearchParams(filterParams).toString()}`)
  }, [adj, pid, navigate, filterParams])

  const handleAdopt = useCallback((adopted: AnnotationResult) => {
    setResult({
      relevance: adopted.relevance,
      labels: [...adopted.labels],
      reason: adopted.reason,
      metadata: adopted.metadata || {},
    })
  }, [])

  const save = useCallback(async (status: string) => {
    if (!row || !schema) return
    const issues = validateAnnotationSelection(schema, result)
    if (issues.length > 0) {
      setSaveError(issues.join('；'))
      return
    }

    setSaving(true)
    setSaveError(null)
    try {
      await updateGenericRow(pid, rid, {
        corrected_result: result,
        reviewer_note: note,
        status,
        version: versionRef.current,
      })
      invalidateListCaches()
      queryClient.invalidateQueries({ queryKey: ['row', pid, rid] })

      if (status === 'approved' || status === 'uncertain') {
        if (undoTimerRef.current) clearTimeout(undoTimerRef.current)
        setUndoData({
          rowId: rid,
          rowNum: row.source_row_number - 1,
          prevStatus: row.status,
          savedStatus: status,
        })
        undoTimerRef.current = setTimeout(() => setUndoData(null), 5000)
        goNext()
      } else {
        setSavedOk(true)
        setTimeout(() => setSavedOk(false), 1500)
        const updated = await api.getRow(pid, rid) as GenericRowDetail
        applyRowToForm(updated, schema)
        queryClient.setQueryData(['row', pid, rid], updated)
      }
    } catch (error) {
      if ((error as { status?: number }).status === 409) {
        const latest = await api.getRow(pid, rid) as GenericRowDetail
        const latestAudit = await api.getAuditLog(pid, rid)
        applyRowToForm(latest, schema)
        setAuditLog(latestAudit)
        queryClient.setQueryData(['row', pid, rid], latest)
        setConflictWarning(`此筆剛被 ${latest.reviewer_username || '他人'} 修改，已更新為最新版本，請確認後再存`)
      } else {
        setSaveError(error instanceof Error ? error.message : '儲存失敗，請重試')
      }
    } finally {
      setSaving(false)
    }
  }, [
    row,
    schema,
    result,
    pid,
    rid,
    note,
    invalidateListCaches,
    queryClient,
    goNext,
    applyRowToForm,
  ])

  const handleUndo = useCallback(async () => {
    if (!undoData) return
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current)
    const { rowId: undoRowId, prevStatus } = undoData
    setUndoData(null)
    await api.updateRow(pid, undoRowId, { status: prevStatus || 'pending' })
    invalidateListCaches()
    queryClient.invalidateQueries({ queryKey: ['row', pid, undoRowId] })
    navigate(`/projects/${pid}/review/${undoRowId}?${new URLSearchParams(filterParams).toString()}`)
  }, [undoData, pid, navigate, filterParams, queryClient, invalidateListCaches])

  useEffect(() => () => {
    if (undoTimerRef.current) clearTimeout(undoTimerRef.current)
  }, [])

  useEffect(() => {
    api.heartbeat(pid, rid).catch(() => {})
    const timer = setInterval(() => api.heartbeat(pid, rid).catch(() => {}), 5000)
    return () => {
      clearInterval(timer)
      api.removePresence(pid, rid).catch(() => {})
    }
  }, [pid, rid])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return
      if (event.key === 'ArrowRight' || event.key === ']') goNext()
      if (event.key === 'ArrowLeft' || event.key === '[') goPrev()
      if (event.key === 'a') save('approved')
      if (event.key === 's') save('corrected')
      if (event.key === 'u') save('uncertain')
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [goNext, goPrev, save])

  const statusInfo: Record<string, { label: string; cls: string }> = {
    pending:   { label: '待審',   cls: 'bg-muted text-muted-foreground' },
    approved:  { label: '已核准', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
    corrected: { label: '已修正', cls: 'bg-primary/10 text-primary' },
    uncertain: { label: '未確定', cls: 'bg-orange-500/20 text-orange-700 ring-1 ring-inset ring-orange-500/25 dark:bg-orange-500/20 dark:text-orange-300' },
  }

  const othersOnRow = presence.filter(entry => entry.row_id === rid && entry.username !== user?.username)
  const validationIssues = schema ? validateAnnotationSelection(schema, result) : []
  const mainText = row?.text || row?.comment_content || ''
  const predictionReason = row
    ? coerceAnnotationResult(row.prediction)?.reason || row.ai_reason
    : ''

  function userColor(username: string) {
    const colors = ['#3b82f6','#8b5cf6','#10b981','#f97316','#ec4899','#14b8a6','#f59e0b','#f43f5e']
    let hash = 0
    for (const char of username) hash = (hash * 31 + char.charCodeAt(0)) & 0xffff
    return colors[hash % colors.length]
  }

  return (
    <div className="min-h-screen pb-20">
      {savedOk && (
        <div className="fixed top-4 right-4 z-50 bg-emerald-600 text-white text-sm px-4 py-2 rounded-lg shadow-lg pointer-events-none flex items-center gap-2">
          <span>✓</span> 已儲存
        </div>
      )}

      {undoData && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 bg-foreground/90 backdrop-blur-sm text-background px-5 py-3 rounded-full shadow-xl text-sm">
          <span>
            {undoData.savedStatus === 'approved' ? '✓' : '?'} 第 {undoData.rowNum} 筆
            已標記為{undoData.savedStatus === 'approved' ? '核准' : '未確定'}
          </span>
          <div className="w-px h-4 bg-background/30" />
          <button onClick={handleUndo} className="font-semibold hover:opacity-70 transition-opacity">撤銷</button>
        </div>
      )}

      <header className="sticky top-0 z-10 backdrop-blur-2xl bg-white/45 dark:bg-black/25 border-b border-black/8 dark:border-white/8 shadow-sm shadow-black/5">
        <div className="max-w-4xl mx-auto px-6 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/projects/${pid}?${new URLSearchParams(filterParams).toString()}`)}
              className="text-muted-foreground px-2"
            >
              ← 返回列表
            </Button>
            {row && (
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusInfo[row.status]?.cls || statusInfo.pending.cls}`}>
                {statusInfo[row.status]?.label || '待審'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {adj && <span className="font-mono text-xs text-muted-foreground">{adj.position} / {adj.total}</span>}
            <Button variant="outline" size="sm" disabled={!adj?.prev_id} onClick={goPrev} title="[ 或 ←">← 上一筆</Button>
            <Button variant="outline" size="sm" disabled={!adj?.next_id} onClick={goNext} title="] 或 →">下一筆 →</Button>
            <Separator orientation="vertical" className="mx-1 h-5" />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setHelpOpen(true)}
              className="w-7 h-7 p-0 rounded-full text-muted-foreground font-semibold text-xs"
            >?</Button>
            <HeaderUserMenu />
          </div>
        </div>
      </header>

      {othersOnRow.length > 0 && (
        <div className="max-w-4xl mx-auto px-6 pt-3">
          <div className="flex items-center gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/40 rounded-xl px-4 py-2.5 text-sm text-amber-700 dark:text-amber-300">
            <div className="flex -space-x-1.5 mr-1">
              {othersOnRow.map(entry => (
                <span
                  key={entry.username}
                  title={entry.username}
                  className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white ring-2 ring-white dark:ring-black/20"
                  style={{ backgroundColor: userColor(entry.username) }}
                >
                  {entry.username[0].toUpperCase()}
                </span>
              ))}
            </div>
            {othersOnRow.map(entry => entry.username).join('、')} 也在查看此筆
          </div>
        </div>
      )}

      {conflictWarning && (
        <div className="max-w-4xl mx-auto px-6 pt-3">
          <div className="flex items-center justify-between bg-orange-50 dark:bg-orange-900/20 border border-orange-200 dark:border-orange-800/40 rounded-xl px-4 py-2.5 text-sm text-orange-700 dark:text-orange-300">
            <span>⚠ {conflictWarning}</span>
            <button onClick={() => setConflictWarning(null)} className="ml-4 text-orange-500 hover:text-orange-700 text-xs">關閉</button>
          </div>
        </div>
      )}

      {loading || !row || !schema ? (
        <div className="flex items-center justify-center py-24 text-muted-foreground text-sm">
          {saveError || '載入中…'}
        </div>
      ) : (
        <main className="max-w-4xl mx-auto px-6 py-6 space-y-4">
          {row.content && row.content !== mainText && (
            <Card>
              <CardContent className="pt-5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">上下文</p>
                <p className="text-foreground text-sm leading-relaxed whitespace-pre-wrap">{row.content}</p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="pt-5">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">主要標注文字</p>
              {mainText
                ? <p className="text-foreground text-sm leading-relaxed whitespace-pre-wrap">{mainText}</p>
                : <p className="text-muted-foreground italic text-sm">（此筆無主要文字）</p>}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-5 space-y-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">分類標注</p>
                <span className="text-[11px] text-muted-foreground">Schema v{schema.version}</span>
              </div>

              <AnnotationFields schema={schema} result={result} onChange={setResult} />

              {predictionReason && (
                <div>
                  <p className={`text-xs font-medium mb-1.5 ${predictionReason.startsWith('⚠️') ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground'}`}>
                    {predictionReason.startsWith('⚠️') ? '⚠ 需人工判斷' : 'AI 判斷理由'}
                  </p>
                  <p className={`text-xs rounded-lg p-3 leading-relaxed ${
                    predictionReason.startsWith('⚠️')
                      ? 'text-red-600 dark:text-red-400 font-medium bg-red-50 dark:bg-red-900/20 ring-1 ring-red-200 dark:ring-red-800/40'
                      : 'text-muted-foreground bg-muted/50'
                  }`}>
                    {predictionReason}
                  </p>
                </div>
              )}

              {row.llm_results && row.llm_results.length > 0 && (
                <LLMComparison results={row.llm_results} schema={schema} onAdopt={handleAdopt} />
              )}

              <div>
                <p className="text-sm font-medium text-foreground mb-1.5">複查備註</p>
                <textarea
                  value={note}
                  onChange={event => setNote(event.target.value)}
                  rows={2}
                  placeholder="可選填：記錄修正原因或備注…"
                  className="w-full border border-input bg-card text-foreground placeholder:text-muted-foreground rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-ring"
                />
              </div>

              {auditLog.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">審查歷史</p>
                  <div className="space-y-1.5">
                    {auditLog.map(entry => {
                      const statusLabel: Record<string, string> = {
                        approved: '核准',
                        corrected: '修正',
                        uncertain: '標記未確定',
                        pending: '還原待審',
                      }
                      const parsedLabels: string[] = entry.labels
                        ? (() => {
                            try {
                              const parsed = JSON.parse(entry.labels)
                              return Array.isArray(parsed) ? parsed : []
                            } catch {
                              return []
                            }
                          })()
                        : []
                      return (
                        <div key={entry.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
                          <span className="font-medium text-foreground">{entry.username}</span>
                          <span className="text-muted-foreground/60">{entry.changed_at.slice(0, 16).replace('T', ' ')}</span>
                          {entry.status && (
                            <span className={`font-medium ${
                              entry.status === 'approved'
                                ? 'text-emerald-600 dark:text-emerald-400'
                                : entry.status === 'corrected'
                                  ? 'text-primary'
                                  : entry.status === 'uncertain'
                                    ? 'text-orange-600 dark:text-orange-400'
                                    : 'text-muted-foreground'
                            }`}>
                              {statusLabel[entry.status] ?? entry.status}
                            </span>
                          )}
                          {entry.relevance && <span className="text-muted-foreground">{entry.relevance}</span>}
                          {parsedLabels.length > 0 && (
                            <span className="text-muted-foreground truncate max-w-xs">[{parsedLabels.join(', ')}]</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {saveError && (
            <div className="bg-destructive/10 border border-destructive/20 rounded-xl px-4 py-3 text-sm text-destructive flex items-center justify-between">
              <span>⚠ {saveError}</span>
              <button onClick={() => setSaveError(null)} className="text-xs text-destructive/70 hover:text-destructive ml-4">關閉</button>
            </div>
          )}

          <div className="flex gap-3">
            <Button
              onClick={() => save('approved')}
              disabled={saving || validationIssues.length > 0}
              className="flex-1 h-12 text-base bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
            >
              ✓ 核准 <span className="text-emerald-200 text-xs ml-1">[A]</span>
            </Button>
            <Button
              onClick={() => save('corrected')}
              disabled={saving || validationIssues.length > 0}
              className="flex-1 h-12 text-base rounded-xl"
            >
              ✎ 儲存修正 <span className="text-primary-foreground/50 text-xs ml-1">[S]</span>
            </Button>
            <Button
              onClick={() => save('uncertain')}
              disabled={saving || validationIssues.length > 0}
              className="flex-1 h-12 text-base rounded-xl bg-orange-500 text-white hover:bg-orange-600 dark:bg-orange-500 dark:hover:bg-orange-600 shadow-sm"
            >
              ? 未確定 <span className="text-orange-100 text-xs ml-1">[U]</span>
            </Button>
          </div>
          <p className="text-center text-xs text-muted-foreground">快捷鍵：← → 切換筆數　A 核准　S 儲存修正　U 未確定</p>
        </main>
      )}

      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent className="sm:max-w-xs">
          <DialogHeader>
            <DialogTitle>快捷鍵說明</DialogTitle>
          </DialogHeader>
          <div className="space-y-1 text-sm">
            {([
              ['←  /  [', '上一筆'],
              ['→  /  ]', '下一筆'],
              ['A', '核准'],
              ['S', '儲存修正'],
              ['U', '標記為未確定'],
            ] as [string, string][]).map(([key, desc]) => (
              <div key={key} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                <kbd className="font-mono text-xs bg-muted px-2 py-1 rounded">{key}</kbd>
                <span className="text-muted-foreground">{desc}</span>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
