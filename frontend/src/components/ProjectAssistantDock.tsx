import { FormEvent, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { Bot, CheckCircle2, FlaskConical, LoaderCircle, Play, Send, Sparkles, Square, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { api, AssistantAction, AssistantMessage } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Button } from '@/components/ui/button'

const TARGET_LABEL = { pending: '待審資料', all: '全部資料', parse_failed: '解析失敗資料' }

function MarkdownMessage({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
      p: props => <p className="mb-2 last:mb-0" {...props} />,
      ul: props => <ul className="my-2 list-disc space-y-1 pl-5" {...props} />,
      ol: props => <ol className="my-2 list-decimal space-y-1 pl-5" {...props} />,
      h1: props => <h1 className="mb-2 mt-3 text-base font-semibold first:mt-0" {...props} />,
      h2: props => <h2 className="mb-2 mt-3 font-semibold first:mt-0" {...props} />,
      h3: props => <h3 className="mb-1.5 mt-3 font-medium first:mt-0" {...props} />,
      code: props => <code className="rounded bg-foreground/8 px-1 py-0.5 font-mono text-[0.8em]" {...props} />,
      pre: props => <pre className="my-2 overflow-x-auto rounded-lg bg-foreground/8 p-3 text-xs" {...props} />,
      blockquote: props => <blockquote className="my-2 border-l-2 border-primary/40 pl-3 text-muted-foreground" {...props} />,
      a: props => <a className="font-medium text-primary underline underline-offset-2" target="_blank" rel="noreferrer" {...props} />,
      table: props => <div className="my-2 overflow-x-auto"><table className="w-full border-collapse text-xs" {...props} /></div>,
      th: props => <th className="border border-border bg-muted/60 px-2 py-1.5 text-left font-medium" {...props} />,
      td: props => <td className="border border-border px-2 py-1.5 align-top" {...props} />,
    }}>{content}</ReactMarkdown>
  )
}

function actionDetails(action: AssistantAction) {
  if (action.type === 'cancel_task') {
    return { icon: Square, title: `停止任務 #${action.task_id}`, details: ['停止等待中或執行中的分類工作'] }
  }
  return {
    icon: action.run_kind === 'trial' ? FlaskConical : Play,
    title: action.run_kind === 'trial' ? '建立試跑任務' : '建立完整分類任務',
    details: [
      `資料範圍：${TARGET_LABEL[action.target]}`,
      `使用結果槽：LLM ${action.slot}`,
      ...(action.run_kind === 'trial' ? [`隨機抽樣：${action.sample_size ?? 10} 筆`] : []),
    ],
  }
}

export default function ProjectAssistantDock() {
  const { user } = useAuth()
  const location = useLocation()
  const queryClient = useQueryClient()
  const projectMatch = location.pathname.match(/^\/projects\/(\d+)/)
  const projectId = projectMatch ? Number(projectMatch[1]) : null
  const rowMatch = location.pathname.match(/\/review\/(\d+)/)
  const rowIds = rowMatch ? [Number(rowMatch[1])] : []
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [executing, setExecuting] = useState<number | null>(null)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMessages([])
    setError('')
    if (!projectId || !user) return
    api.listAssistantMessages(projectId).then(setMessages).catch(error => setError(error instanceof Error ? error.message : '無法載入任務助手'))
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
      action: null, action_status: null, action_result: null,
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

  const execute = async (messageId: number) => {
    setExecuting(messageId)
    setError('')
    try {
      const { result } = await api.executeAssistantAction(projectId, messageId)
      setMessages(current => current.map(message => message.id === messageId
        ? { ...message, action_status: 'completed', action_result: result }
        : message))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['tasks', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['project', projectId] }),
      ])
    } catch (error) {
      setError(error instanceof Error ? error.message : '操作執行失敗')
    } finally {
      setExecuting(null)
    }
  }

  return (
    <div className="fixed inset-x-3 bottom-3 z-[80] flex flex-col items-end gap-3 sm:inset-x-auto sm:bottom-6 sm:left-6 sm:items-start">
      {open && (
        <section data-slot="card" className="flex h-[min(39rem,calc(100vh-6rem))] w-full flex-col overflow-hidden rounded-3xl border border-white/40 bg-popover/90 text-card-foreground shadow-[0_24px_80px_oklch(0.2_0.08_255/0.22)] backdrop-blur-2xl sm:w-[26rem] dark:border-white/10">
          <header className="relative flex items-center justify-between border-b border-border/70 px-4 py-3.5">
            <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-primary/50 to-transparent" />
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/20"><Sparkles size={17} /></div>
              <div><p className="text-sm font-semibold tracking-tight">專案任務助手</p><p className="text-[11px] text-muted-foreground">OpenClaw · 操作前會先讓你確認</p></div>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="關閉任務助手"><X size={17} /></Button>
          </header>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 [scrollbar-gutter:stable]">
            {messages.length === 0 && (
              <div className="rounded-2xl border border-border/70 bg-muted/40 p-4 text-sm leading-6 text-muted-foreground">
                <p className="font-medium text-foreground">今天想推進哪一項工作？</p>
                <p className="mt-1">可以請我查看進度、規劃試跑、建立分類任務，或停止執行中的任務。</p>
                {rowIds.length > 0 && <p className="mt-2 text-xs text-primary">目前資料列已加入對話脈絡。</p>}
              </div>
            )}
            {messages.map(message => {
              const proposal = message.action ? actionDetails(message.action) : null
              const ProposalIcon = proposal?.icon
              const isExecuting = executing === message.id
              return (
                <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[91%] ${message.role === 'user' ? '' : 'w-full'}`}>
                    <div className={`rounded-2xl px-3.5 py-2.5 text-sm leading-6 ${message.role === 'user' ? 'rounded-br-md bg-primary text-primary-foreground shadow-sm' : 'rounded-bl-md border border-border/60 bg-card/75'}`}>
                      {message.role === 'assistant' ? <MarkdownMessage content={message.content} /> : message.content}
                    </div>
                    {proposal && (
                      <div className="mt-2 overflow-hidden rounded-2xl border border-primary/20 bg-primary/[0.045]">
                        <div className="flex gap-3 p-3.5">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">{ProposalIcon && <ProposalIcon size={17} />}</div>
                          <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{proposal.title}</p><ul className="mt-1 space-y-0.5 text-xs leading-5 text-muted-foreground">{proposal.details.map(detail => <li key={detail}>{detail}</li>)}</ul></div>
                        </div>
                        <div className="flex items-center justify-between border-t border-primary/10 bg-background/35 px-3.5 py-2.5">
                          {message.action_status === 'completed' ? (
                            <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400"><CheckCircle2 size={14} /> {message.action_result?.message ?? '操作完成'}</span>
                          ) : (
                            <><span className="text-[11px] text-muted-foreground">確認後才會執行</span><Button size="sm" onClick={() => execute(message.id)} disabled={isExecuting}>{isExecuting ? <><LoaderCircle className="animate-spin" />執行中</> : '確認執行'}</Button></>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
            {sending && <div className="flex items-center gap-2 text-xs text-muted-foreground"><LoaderCircle size={14} className="animate-spin" />正在理解專案與任務狀態…</div>}
            <div ref={endRef} />
          </div>

          <form onSubmit={send} className="border-t border-border/70 bg-background/25 p-3">
            {error && <p className="mb-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>}
            <div className="flex items-end gap-2 rounded-2xl border border-input bg-background/75 p-1.5 shadow-inner focus-within:ring-2 focus-within:ring-ring/30">
              <textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} rows={2} placeholder="例如：先用 10 筆待審資料試跑 LLM 1" className="min-h-10 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground/70" />
              <Button type="submit" size="icon" className="rounded-xl" disabled={!input.trim() || sending} aria-label="傳送"><Send size={16} /></Button>
            </div>
            <p className="mt-1.5 px-1 text-[10px] text-muted-foreground">Enter 傳送 · Shift + Enter 換行</p>
          </form>
        </section>
      )}
      <button type="button" onClick={() => setOpen(value => !value)} className="group flex min-h-12 items-center gap-2.5 rounded-2xl border border-white/30 bg-primary px-4 py-3 text-sm font-medium text-primary-foreground shadow-[0_12px_36px_oklch(0.35_0.18_255/0.3)] transition hover:-translate-y-0.5 hover:shadow-[0_16px_42px_oklch(0.35_0.18_255/0.36)] dark:border-white/10"><Bot size={18} className="transition-transform group-hover:scale-110" /> 任務助手</button>
    </div>
  )
}
