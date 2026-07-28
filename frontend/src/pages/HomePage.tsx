import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, Project } from '../api/client'
import { useAuth } from '../context/AuthContext'
import HeaderUserMenu from '../components/HeaderUserMenu'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardAction } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'

export default function HomePage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [newName, setNewName] = useState('')
  const [newFile, setNewFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = () => {
    setLoading(true)
    api.listProjects().then(setProjects).catch(() => setError('載入失敗')).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleUpload = async () => {
    if (!newName.trim() || !newFile) return
    setUploading(true)
    setError(null)
    try {
      await api.createProject(newName.trim(), newFile)
      setShowModal(false)
      setNewName('')
      setNewFile(null)
      load()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (proj: Project) => {
    if (!window.confirm(`確定要刪除「${proj.name}」嗎？\n所有標注進度都會消失。`)) return
    await api.deleteProject(proj.id)
    load()
  }

  const closeModal = () => { setShowModal(false); setError(null) }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 backdrop-blur-2xl bg-white/45 dark:bg-black/25 border-b border-black/8 dark:border-white/8 shadow-sm shadow-black/5">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-heading font-semibold text-foreground">標注複查平台</h1>
            <p className="text-xs text-muted-foreground mt-0.5">管理並複查 AI 標注結果</p>
          </div>
          <div className="flex items-center gap-3">
            <HeaderUserMenu />
            {(user?.role === 'admin' || user?.role === 'reviewer') && (
              <Button onClick={() => setShowModal(true)} size="sm">
                + 新增專案
              </Button>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-6 px-4 py-3 bg-destructive/10 border border-destructive/20 text-destructive rounded-lg text-sm">{error}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-24 text-muted-foreground text-sm">載入中…</div>
        ) : projects.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <div className="text-5xl">📋</div>
            <p className="text-foreground font-medium">還沒有任何專案</p>
            <p className="text-muted-foreground text-sm">點擊「新增專案」上傳 CSV 開始標注複查</p>
            {(user?.role === 'admin' || user?.role === 'reviewer') && (
              <Button onClick={() => setShowModal(true)} className="mt-2">+ 新增專案</Button>
            )}
          </div>
        ) : (
          <div className="grid gap-4">
            {projects.map(proj => {
              const reviewed = (proj.approved || 0) + (proj.corrected || 0)
              const total = proj.total_rows || 1
              const pctApproved = Math.round(((proj.approved || 0) / total) * 100)
              const pctCorrected = Math.round(((proj.corrected || 0) / total) * 100)
              const pctTotal = Math.round((reviewed / total) * 100)
              return (
                <Card key={proj.id}>
                  <CardHeader>
                    <CardTitle>{proj.name}</CardTitle>
                    <CardDescription>{proj.filename} · {proj.created_at?.slice(0, 10)}</CardDescription>
                    <CardAction>
                      <div className="flex items-center gap-1.5">
                        <Button variant="outline" size="sm"
                          onClick={() => api.exportProject(proj.id, `${proj.name}.xlsx`).catch(e => alert(e.message))}>
                          匯出
                        </Button>
                        <Button size="sm" onClick={() => navigate(`/projects/${proj.id}`)}>
                          開始複查
                        </Button>
                        {(user?.role === 'admin' || user?.role === 'reviewer') && (
                          <Button variant="destructive" size="sm" onClick={() => handleDelete(proj)}>
                            刪除
                          </Button>
                        )}
                      </div>
                    </CardAction>
                  </CardHeader>
                  <CardContent>
                    <div className="flex gap-5 text-sm mb-3">
                      <span className="text-muted-foreground">共 <strong className="text-foreground font-semibold">{proj.total_rows}</strong> 筆</span>
                      <span className="text-emerald-600 dark:text-emerald-400 font-medium">✓ 核准 {proj.approved || 0}</span>
                      <span className="text-primary font-medium">✎ 修正 {proj.corrected || 0}</span>
                      <span className="text-orange-600 dark:text-orange-400 font-semibold">? 未確定 {proj.uncertain || 0}</span>
                      <span className="text-muted-foreground">⏳ 待審 {proj.pending ?? proj.total_rows}</span>
                    </div>
                    <div className="h-1.5 bg-black/10 dark:bg-white/15 rounded-full overflow-hidden flex">
                      <div className="bg-emerald-500 h-full transition-all duration-500" style={{ width: `${pctApproved}%` }} />
                      <div className="bg-primary h-full transition-all duration-500" style={{ width: `${pctCorrected}%` }} />
                      <div className="bg-orange-500 h-full transition-all duration-500"
                        style={{ width: `${((proj.uncertain || 0) / total) * 100}%` }} />
                    </div>
                    <p className="text-xs text-muted-foreground mt-1.5">{reviewed} / {proj.total_rows} 已審查 ({pctTotal}%)</p>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </main>

      <Dialog open={showModal} onOpenChange={(o) => { if (!o) closeModal() }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新增專案</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="space-y-1.5">
              <Label htmlFor="project-name">專案名稱</Label>
              <Input id="project-name" value={newName} onChange={e => setNewName(e.target.value)}
                placeholder="例：2025 Q2 標注" autoFocus />
            </div>
            <div className="space-y-1.5">
              <Label>資料檔案</Label>
              <div onClick={() => fileRef.current?.click()}
                className="border-2 border-dashed border-input rounded-lg p-6 text-center cursor-pointer hover:border-primary/50 transition-colors">
                {newFile ? (
                  <p className="text-sm text-primary font-medium">{newFile.name}</p>
                ) : (
                  <>
                    <p className="text-sm text-muted-foreground">點擊選擇檔案</p>
                    <p className="text-xs text-muted-foreground/60 mt-1">支援 CSV（UTF-8 / Big5）或 XLSX</p>
                  </>
                )}
              </div>
              <input ref={fileRef} type="file" accept=".csv,.xlsx,.xls" className="hidden"
                onChange={e => setNewFile(e.target.files?.[0] || null)} />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeModal}>取消</Button>
            <Button onClick={handleUpload} disabled={!newName.trim() || !newFile || uploading}>
              {uploading ? '上傳中…' : '建立專案'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
