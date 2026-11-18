import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, Project } from '../api/client'
import { useAuth } from '../context/AuthContext'
import HeaderUserMenu from '../components/HeaderUserMenu'
import ImportWizardDialog from '../components/ImportWizardDialog'
import { ArrowRight, Check, CircleHelp, Clock3, Download, FileText, FolderOpen, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardAction } from '@/components/ui/card'

export default function HomePage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [showWizard, setShowWizard] = useState(false)
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    api.listProjects().then(setProjects).catch(() => setError('載入失敗')).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (proj: Project) => {
    if (!window.confirm(`確定要刪除「${proj.name}」嗎？\n所有標注進度都會消失。`)) return
    await api.deleteProject(proj.id)
    load()
  }

  const canCreate = user?.role === 'admin' || user?.role === 'reviewer'
  const visibleProjects = projects.filter(project => `${project.name} ${project.filename}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))

  return (
    <div className="home-workspace min-h-screen">
      <header className="sticky top-0 z-40 backdrop-blur-2xl bg-white/45 dark:bg-black/25 border-b border-black/8 dark:border-white/8 shadow-sm shadow-black/5">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="workspace-brand">
            <img src="/favicon.svg" alt="" width="38" height="38" />
            <div>
              <p className="text-base font-semibold tracking-tight">LLM Label</p>
              <p className="text-xs text-muted-foreground mt-0.5">標注複查平台</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {canCreate && (
              <Button onClick={() => setShowWizard(true)} size="sm"><Plus aria-hidden="true" />新增專案</Button>
            )}
            <HeaderUserMenu />
          </div>
        </div>
      </header>

      <main id="main-content" className="max-w-6xl mx-auto px-6 py-8">
        <section className="workspace-intro" aria-labelledby="workspace-title">
          <div>
            <h1 id="workspace-title" className="text-2xl font-semibold tracking-tight">專案工作台</h1>
            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">管理資料集、標籤 Schema 與 AI / 人工標注結果</p>
          </div>
          {!loading && projects.length > 0 && <p className="workspace-count"><FolderOpen aria-hidden="true" size={16} />{projects.length} 個專案<span aria-hidden="true">·</span>{projects.reduce((sum, project) => sum + project.total_rows, 0).toLocaleString()} 筆資料</p>}
        </section>
        {projects.length > 0 && <div className="workspace-toolbar">
          <h2 className="text-sm font-semibold">所有專案 <span className="text-muted-foreground font-normal ml-1">{visibleProjects.length}</span></h2>
          <div className="relative w-full sm:w-72">
            <Search aria-hidden="true" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label="搜尋專案名稱或檔名" placeholder="搜尋專案名稱或檔名…" value={search} onChange={event => setSearch(event.target.value)} className="pl-9" />
          </div>
        </div>}
        {error && <div role="alert" className="mb-6 flex items-center justify-between gap-4 px-4 py-3 bg-destructive/10 border border-destructive/20 text-destructive rounded-lg text-sm"><span>無法載入專案，請稍後重試。</span><Button variant="outline" size="sm" onClick={load}>重新載入</Button></div>}

        {loading ? (
          <div role="status" aria-label="正在載入專案" className="grid gap-4"><span className="sr-only">載入中…</span>{[0, 1, 2].map(index => <div key={index} className="project-skeleton" aria-hidden="true"><div /><div /><div /></div>)}</div>
        ) : !error && projects.length === 0 ? (
          <div className="workspace-empty flex flex-col items-center justify-center py-20 px-6 gap-3 text-center">
            <FolderOpen aria-hidden="true" className="text-primary mb-2" size={36} strokeWidth={1.5} />
            <p className="text-foreground font-medium">還沒有任何專案</p>
            <p className="text-muted-foreground text-sm">上傳資料後設定欄位 Mapping、標籤與標注規則</p>
            {canCreate && (
              <Button onClick={() => setShowWizard(true)} className="mt-2"><Plus aria-hidden="true" />新增專案</Button>
            )}
          </div>
        ) : error && projects.length === 0 ? null : visibleProjects.length === 0 ? (
          <div className="workspace-empty text-center py-16 px-6">
            <Search aria-hidden="true" size={28} className="mx-auto mb-4 text-muted-foreground" />
            <p className="font-medium">沒有符合的專案</p>
            <p className="text-sm text-muted-foreground mt-2">試試其他專案名稱或檔名。</p>
            <Button variant="outline" onClick={() => setSearch('')} className="mt-5">清除搜尋</Button>
          </div>
        ) : (
          <div className="grid gap-4">
            {visibleProjects.map(proj => {
              const reviewed = (proj.approved || 0) + (proj.corrected || 0)
              const total = proj.total_rows || 1
              const pctApproved = ((proj.approved || 0) / total) * 100
              const pctCorrected = ((proj.corrected || 0) / total) * 100
              const pctTotal = Math.round((reviewed / total) * 100)
              return (
                <Card key={proj.id} className="project-card">
                  <CardHeader>
                    <CardTitle><button className="project-title" onClick={() => navigate(`/projects/${proj.id}`)}>{proj.name}</button></CardTitle>
                    <CardDescription className="flex items-center gap-1.5 min-w-0"><FileText aria-hidden="true" size={14} className="shrink-0" /><span className="truncate">{proj.filename}</span><span className="shrink-0">· {proj.created_at?.slice(0, 10)}</span></CardDescription>
                    <CardAction>
                      <div className="flex items-center gap-1.5">
                        <Button variant="outline" size="sm" onClick={() => api.exportProject(proj.id, `${proj.name}.xlsx`).catch(e => alert(e.message))}><Download aria-hidden="true" />匯出</Button>
                        <Button size="sm" onClick={() => navigate(`/projects/${proj.id}`)}>開始複查<ArrowRight aria-hidden="true" /></Button>
                        {canCreate && (
                          <Button variant="ghost" size="icon-sm" aria-label={`刪除專案「${proj.name}」`} title="刪除專案" className="text-muted-foreground hover:text-destructive hover:bg-destructive/10" onClick={() => handleDelete(proj)}><Trash2 aria-hidden="true" /></Button>
                        )}
                      </div>
                    </CardAction>
                  </CardHeader>
                  <CardContent>
                    <div className="project-status flex flex-wrap gap-x-5 gap-y-2 text-xs mb-4">
                      <span className="text-muted-foreground">共 <strong className="text-foreground font-semibold">{proj.total_rows}</strong> 筆</span>
                      <span className="text-emerald-700 dark:text-emerald-400 font-medium"><Check aria-hidden="true" size={13} />核准 {proj.approved || 0}</span>
                      <span className="text-primary font-medium"><Pencil aria-hidden="true" size={13} />修正 {proj.corrected || 0}</span>
                      <span className="text-orange-700 dark:text-orange-400 font-semibold"><CircleHelp aria-hidden="true" size={13} />未確定 {proj.uncertain || 0}</span>
                      <span className="text-muted-foreground"><Clock3 aria-hidden="true" size={13} />待審 {proj.pending ?? proj.total_rows}</span>
                    </div>
                    <div role="img" aria-label={`核准 ${proj.approved || 0} 筆、修正 ${proj.corrected || 0} 筆、未確定 ${proj.uncertain || 0} 筆，共 ${proj.total_rows} 筆`} className="h-1.5 bg-black/7 dark:bg-white/10 rounded-full overflow-hidden flex">
                      <div className="bg-emerald-500 h-full transition-all duration-500" style={{ width: `${pctApproved}%` }} />
                      <div className="bg-primary h-full transition-all duration-500" style={{ width: `${pctCorrected}%` }} />
                      <div className="bg-orange-500 h-full transition-all duration-500" style={{ width: `${((proj.uncertain || 0) / total) * 100}%` }} />
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground mt-3 tabular-nums"><span>{reviewed.toLocaleString()} / {proj.total_rows.toLocaleString()} 已審查</span><span className="font-semibold text-foreground">{pctTotal}%</span></div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </main>

      <ImportWizardDialog
        open={showWizard}
        onOpenChange={setShowWizard}
        onCreated={projectId => {
          load()
          navigate(`/projects/${projectId}`)
        }}
      />
    </div>
  )
}
