import { Moon, Sun } from 'lucide-react'

interface Props {
  isDark: boolean
  toggle: () => void
}

export default function DarkToggle({ isDark, toggle }: Props) {
  return (
    <button
      onClick={toggle}
      aria-label={isDark ? '切換亮色模式' : '切換深色模式'}
      title={isDark ? '切換亮色模式' : '切換深色模式'}
      className="w-10 h-10 flex items-center justify-center rounded-xl border border-border bg-card text-muted-foreground hover:bg-accent hover:text-foreground transition-colors focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
    >
      {isDark ? <Sun aria-hidden="true" size={17} /> : <Moon aria-hidden="true" size={17} />}
    </button>
  )
}
