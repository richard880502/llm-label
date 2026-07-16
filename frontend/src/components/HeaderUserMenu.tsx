import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useDarkMode } from '../hooks/useDarkMode'

export default function HeaderUserMenu() {
  const { user, logout } = useAuth()
  const { isDark, toggle } = useDarkMode()
  const initial = user?.username?.[0]?.toUpperCase() ?? '?'

  return (
    <div className="flex items-center gap-1">
      <button
        onClick={toggle}
        title={isDark ? '切換亮色模式' : '切換深色模式'}
        className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 dark:text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-sm"
      >
        {isDark ? '☀️' : '🌙'}
      </button>

      {user?.role === 'admin' && (
        <Link to="/users"
          className="hidden sm:block text-xs px-2.5 py-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors">
          使用者管理
        </Link>
      )}

      <div className="w-px h-5 bg-gray-200 dark:bg-gray-600 mx-1" />

      <div className="flex items-center gap-2 px-1">
        <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300 text-xs font-bold flex items-center justify-center select-none shrink-0">
          {initial}
        </div>
        <span className="hidden sm:block text-sm font-medium text-gray-700 dark:text-gray-200 max-w-[100px] truncate">
          {user?.username}
        </span>
      </div>

      <button onClick={logout} title="登出"
        className="text-xs px-2.5 py-1.5 text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors">
        登出
      </button>
    </div>
  )
}
