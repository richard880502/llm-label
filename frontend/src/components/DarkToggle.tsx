interface Props {
  isDark: boolean
  toggle: () => void
}

export default function DarkToggle({ isDark, toggle }: Props) {
  return (
    <button
      onClick={toggle}
      title={isDark ? '切換亮色模式' : '切換深色模式'}
      className="w-9 h-9 flex items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-base"
    >
      {isDark ? '☀️' : '🌙'}
    </button>
  )
}
