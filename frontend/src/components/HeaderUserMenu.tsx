import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useDarkMode } from '../hooks/useDarkMode'
import DarkToggle from './DarkToggle'
import ProjectTaskDock from './ProjectTaskDock'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export default function HeaderUserMenu() {
  const { user, logout } = useAuth()
  const { isDark, toggle } = useDarkMode()
  const location = useLocation()
  const navigate = useNavigate()
  const initial = user?.username?.[0]?.toUpperCase() ?? '?'
  const projectMatch = location.pathname.match(/^\/projects\/(\d+)/)
  const projectId = projectMatch ? Number(projectMatch[1]) : null

  return (
    <>
      <div className="flex items-center gap-1">
        <DarkToggle isDark={isDark} toggle={toggle} />

        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={`開啟 ${user?.username || ''} 的帳號選單`}
            className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2">
            <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 text-xs font-bold flex items-center justify-center select-none shrink-0">
              {initial}
            </div>
            <span className="hidden sm:block text-sm font-medium text-gray-700 dark:text-gray-200 max-w-[100px] truncate">
              {user?.username}
            </span>
            <span className="text-[10px] text-muted-foreground">▾</span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuGroup>
              <DropdownMenuLabel>{user?.username}（{user?.role === 'admin' ? '管理員' : '審查者'}）</DropdownMenuLabel>
              {user?.role === 'admin' && (
                <DropdownMenuItem onClick={() => navigate('/users')}>使用者管理</DropdownMenuItem>
              )}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={logout}>登出</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {projectId !== null && <ProjectTaskDock projectId={projectId} />}
    </>
  )
}
