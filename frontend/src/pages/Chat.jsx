import { useEffect, useRef, useState } from 'react'
import { MessageSquare, Send, Wrench } from 'lucide-react'
import { api } from '../api'
import { Markdown } from '@/components/markdown'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const SUGGESTIONS = [
  'How is my portfolio doing today?',
  'Should I trim NVDA before earnings?',
  'Score DHR - is it a buy right now?',
  'Any unusual options activity on my positions?',
]

const TOOL_LABELS = {
  get_portfolio: 'portfolio',
  get_market: 'market',
  get_snapshot: 'snapshot',
  get_score: 'scorer',
  get_news: 'news',
  get_options_flow: 'options flow',
  get_insider: 'insider',
}

function Message({ m }) {
  const isUser = m.role === 'user'
  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cn(
        'max-w-[85%] rounded-xl px-4 py-2.5',
        isUser ? 'bg-primary text-primary-foreground text-sm' : 'bg-card border',
      )}>
        {isUser ? m.content : <Markdown>{m.content}</Markdown>}
        {!isUser && m.toolCalls?.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1 border-t pt-2">
            <Wrench className="size-3 text-muted-foreground" />
            {[...new Set(m.toolCalls)].map(t => (
              <Badge key={t} variant="outline" className="text-[10px] font-normal">
                {TOOL_LABELS[t] ?? t}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  async function send(text) {
    const content = (text ?? input).trim()
    if (!content || busy) return
    setInput('')
    const next = [...messages, { role: 'user', content }]
    setMessages(next)
    setBusy(true)
    try {
      const res = await api.chat({
        messages: next.map(({ role, content }) => ({ role, content })),
      })
      setMessages(m => [...m, { role: 'assistant', content: res.reply, toolCalls: res.tool_calls }])
    } catch (e) {
      setMessages(m => [...m, { role: 'assistant', content: `Something went wrong: ${e.message}` }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-8.5rem)] max-w-3xl flex-col gap-4">
      <div className="flex-1 space-y-4 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <Card className="mt-8">
            <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
              <div className="flex size-10 items-center justify-center rounded-full bg-muted">
                <MessageSquare className="size-5 text-muted-foreground" />
              </div>
              <div>
                <p className="font-medium">Ask the AI analyst about your portfolio</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  It answers by actually running the system - live snapshots, the scoring
                  engine, news, options flow, and insider signals.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map(s => (
                  <Button key={s} variant="outline" size="sm" onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
        {messages.map((m, i) => <Message key={i} m={m} />)}
        {busy && (
          <div className="flex justify-start">
            <div className="rounded-xl border bg-card px-4 py-2.5 text-sm text-muted-foreground">
              Running tools<span className="animate-pulse">…</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form
        onSubmit={e => { e.preventDefault(); send() }}
        className="flex gap-2"
      >
        <Input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about a position, a ticker, the market…"
          disabled={busy}
        />
        <Button type="submit" size="icon" disabled={busy || !input.trim()}>
          <Send />
        </Button>
      </form>
    </div>
  )
}
