import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

const TABS = [
  { label: '資料列表', path: '' },
  { label: '標注傾向', path: '/tendency' },
]

function ProgressSummary({ projectId }: { projectId: number }) {
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.getProject(projectId),
  })
  if (!project || !project.total_rows) return null
  const total = project.total_rows
  const parts = [
    { label: '已核准', value: project.approved || 0, color: 'bg-emerald-500' },
    { label: '已修正', value: project.corrected || 0, color: 'bg-primary' },
    { label: '未確定', value: project.uncertain || 0, color: 'bg-orange-500' },
  ]
  const pending = project.pending ?? total - parts.reduce((a, p) => a + p.value, 0)
  const done = parts[0].value + parts[1].value
  return (
    <div className="group relative flex items-center gap-2.5 text-xs" tabIndex={0}>
      <span className="text-muted-foreground whitespace-nowrap">
        已審 <span className="font-semibold text-foreground tabular-nums">{done.toLocaleString()}</span>
        {' '}/ {total.toLocaleString()}
      </span>
      <div className="hidden sm:flex h-1.5 w-28 gap-[2px] rounded-full bg-muted overflow-hidden">
        {parts.map(p => p.value > 0 && (
          <div key={p.label} className={`h-full ${p.color}`} style={{ width: `${p.value / total * 100}%` }} />
        ))}
      </div>
      <span className="font-medium tabular-nums">{Math.round(done / total * 100)}%</span>
      <div className="invisible opacity-0 group-hover:visible group-hover:opacity-100 group-focus:visible group-focus:opacity-100 transition-opacity absolute right-0 top-full mt-2 z-50 w-44 rounded-lg border bg-popover text-popover-foreground shadow-md p-2.5 space-y-1.5">
        {[...parts, { label: '待審', value: pending, color: 'bg-muted-foreground/30' }].map(p => (
          <div key={p.label} className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-sm ${p.color}`} />
            <span className="flex-1">{p.label}</span>
            <span className="tabular-nums">{p.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Second header row: project tabs on the left, progress and page actions on the right. */
export default function ProjectNav({ projectId, actions }: { projectId: number; actions?: ReactNode }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const base = `/projects/${projectId}`
  const current = pathname.slice(base.length)

  return (
    <div className="max-w-6xl mx-auto px-6 flex flex-wrap items-center gap-x-4 gap-y-2">
      <nav className="flex items-center gap-1 -mb-px overflow-x-auto" aria-label="專案頁面">
        {TABS.map(tab => {
          const active = tab.path === '' ? current === '' || current === '/' : current.startsWith(tab.path)
          return (
            <button key={tab.label} onClick={() => navigate(base + tab.path)}
              aria-current={active ? 'page' : undefined}
              className={`px-3 py-2.5 text-sm whitespace-nowrap border-b-2 transition-colors ${active
                ? 'border-primary text-foreground font-medium'
                : 'border-transparent text-muted-foreground hover:text-foreground'}`}>
              {tab.label}
            </button>
          )
        })}
      </nav>
      <div className="flex-1" />
      <ProgressSummary projectId={projectId} />
      {actions && <div className="flex items-center gap-1.5 py-1.5">{actions}</div>}
    </div>
  )
}
