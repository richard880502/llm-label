import { FormEvent, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Bot, Send, X } from 'lucide-react'

import { api, AssistantMessage } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Button } from '@/components/ui/button'


export default function ProjectAssistantDock() {
  const { user } = useAuth()
  const location = useLocation()
  const projectMatch = location.pathname.match(/^\/projects\/(\d+)/)
  const projectId = projectMatch ? Number(projectMatch[1]) : null
  const rowMatch = location.pathname.match(/\/review\/(\d+)/)
  const rowIds = rowMatch ? [Number(rowMatch[1])] : []
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMessages([])
    setError('')
    if (!projectId || !user) return
    api.listAssistantMessages(projectId)
      .then(setMessages)
      .catch(error => setError(error instanceof Error ? error.message : '無法載入任務助手'))
  }, [projectId, user])

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [open, messages, sending])

  if (!projectId || !user) return null

  const send = async (event: FormEvent) => {
    event.preventDefault()
    const message = input.trim()
    if (!message || sending) return
    const optimistic: AssistantMessage = {
      id: -Date.now(), role: 'user', content: message, source: 'web', created_at: '',
    }
    setMessages(current => [...current, optimistic])
    setInput('')
    setError('')
    setSending(true)
    try {
      const reply = await api.sendAssistantMessage(projectId, message, rowIds)
      setMessages(current => [...current, reply])
    } catch (error) {
      setMessages(current => current.filter(item => item.id !== optimistic.id))
      setInput(message)
      setError(error instanceof Error ? error.message : '任務助手暫時無法回覆')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="fixed bottom-6 left-6 z-[80] flex flex-col items-start gap-2">
      {open && (
        <section className="flex h-[min(36rem,calc(100vh-8rem))] w-[min(25rem,calc(100vw-3rem))] flex-col overflow-hidden rounded-2xl border border-border bg-popover/95 shadow-2xl backdrop-blur-xl">
          <header className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary"><Bot size={17} /></div>
              <div>
                <p className="text-sm font-semibold">專案任務助手</p>
                <p className="text-[11px] text-muted-foreground">理解專案狀態並協助推進下一步</p>
              </div>
            </div>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => setOpen(false)} aria-label="關閉任務助手"><X size={16} /></Button>
          </header>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="rounded-xl bg-muted/50 p-4 text-sm leading-6 text-muted-foreground">
                你可以問我目前任務進度、哪些資料值得優先複查，或描述想改善的標籤規則。
                {rowIds.length > 0 && <p className="mt-2 text-xs text-primary">目前這筆資料會一起提供給助手。</p>}
              </div>
            )}
            {messages.map(message => (
              <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${
                  message.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground'
                }`}>
                  {message.content}
                </div>
              </div>
            ))}
            {sending && <div className="text-xs text-muted-foreground">正在整理專案狀態…</div>}
            <div ref={endRef} />
          </div>

          <form onSubmit={send} className="border-t border-border p-3">
            {error && <p className="mb-2 text-xs text-destructive">{error}</p>}
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={event => setInput(event.target.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    event.currentTarget.form?.requestSubmit()
                  }
                }}
                rows={2}
                placeholder="例如：幫我找出下一步該處理的任務"
                className="min-h-11 flex-1 resize-none rounded-xl border border-input bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
              />
              <Button type="submit" className="h-11 w-11 rounded-xl p-0" disabled={!input.trim() || sending} aria-label="傳送"><Send size={17} /></Button>
            </div>
          </form>
        </section>
      )}
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        className="flex min-h-12 items-center gap-2 rounded-full border border-primary/30 bg-primary px-4 py-3 text-sm font-medium text-primary-foreground shadow-xl transition hover:opacity-90"
      >
        <Bot size={18} /> 任務助手
      </button>
    </div>
  )
}
