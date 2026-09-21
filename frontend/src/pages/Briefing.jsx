import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles, RefreshCw, Swords } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api'
import { Markdown } from '@/components/markdown'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'

function DebateCard() {
  const [ticker, setTicker] = useState('')
  const [running, setRunning] = useState(false)
  const [debate, setDebate] = useState(null)

  async function run() {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setRunning(true)
    try {
      const res = await api.debate(t)
      if (res.available === false) {
        toast.error(res.reason || 'AI unavailable')
      } else {
        setDebate(res)
      }
    } catch (e) {
      toast.error(e.message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-semibold">
          <Swords className="size-4" /> Bull vs Bear Debate
        </CardTitle>
        <p className="mt-1 text-xs text-muted-foreground">
          Two AI analysts argue opposite sides of a ticker, then a judge delivers a verdict.
          Takes 30-60 seconds.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1.5">
          <div className="flex gap-2">
            <Input
              className="w-32 uppercase"
              placeholder="Ticker"
              value={ticker}
              onChange={e => setTicker(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !running && run()}
            />
            <Button onClick={run} disabled={running || !ticker.trim()}>
              <Swords className={running ? 'animate-pulse' : ''} />
              {running ? 'Debating…' : 'Run debate'}
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            3 small AI calls - costs about a cent.
          </p>
        </div>

        {debate && (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold tracking-wider text-gain">
                    BULL
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Markdown>{debate.bull}</Markdown>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold tracking-wider text-loss">
                    BEAR
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Markdown>{debate.bear}</Markdown>
                </CardContent>
              </Card>
            </div>
            <div className="border-t pt-4">
              <div className="mb-2 text-sm font-semibold tracking-wider">
                VERDICT - {debate.ticker}
              </div>
              <Markdown>{debate.verdict}</Markdown>
            </div>
            {debate.usage_today?.cost_usd != null && (
              <p className="tnum text-xs text-muted-foreground">
                AI spend today ${debate.usage_today.cost_usd.toFixed(2)}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Briefing() {
  const queryClient = useQueryClient()
  const [generating, setGenerating] = useState(false)
  const latestQ = useQuery({ queryKey: ['briefing-latest'], queryFn: api.briefingLatest })

  async function generate() {
    setGenerating(true)
    try {
      const res = await api.briefing()
      if (res.available === false) {
        toast.error(res.reason || 'AI unavailable')
      } else {
        queryClient.setQueryData(['briefing-latest'], res)
        toast.success(res.cached ? "Loaded today's briefing" : 'Briefing generated')
      }
    } catch (e) {
      toast.error(e.message)
    } finally {
      setGenerating(false)
    }
  }

  if (latestQ.isLoading) return <Skeleton className="h-[400px] rounded-xl" />

  const b = latestQ.data
  const hasBriefing = b?.available && b?.markdown

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base font-semibold">
              <Sparkles className="size-4" /> AI Morning Briefing
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Generated from live market data, your positions, and today's headlines.
              Takes 30-60 seconds.
            </p>
          </div>
          <Button onClick={generate} disabled={generating}>
            <RefreshCw className={generating ? 'animate-spin' : ''} />
            {generating ? 'Generating…' : hasBriefing ? 'Regenerate' : 'Generate'}
          </Button>
        </CardHeader>
        {hasBriefing && (
          <CardContent className="flex flex-wrap items-center gap-2 border-t pt-4 text-xs text-muted-foreground">
            <Badge variant="outline" className="font-normal">{b.date}</Badge>
            <Badge variant="secondary" className="font-normal">{b.model}</Badge>
            {b.usage_today?.cost_usd != null && (
              <Badge variant="outline" className="tnum font-normal">
                AI spend today ${b.usage_today.cost_usd.toFixed(2)}
              </Badge>
            )}
            <span>covers {b.tickers_covered?.length ?? 0} tickers</span>
          </CardContent>
        )}
      </Card>

      {!hasBriefing && !generating && (
        <Alert>
          <AlertDescription>
            {b?.reason
              ? `No briefing available - ${b.reason}`
              : 'No briefing generated yet today. Click Generate to run the AI analyst.'}
          </AlertDescription>
        </Alert>
      )}

      {generating && !hasBriefing && <Skeleton className="h-[400px] rounded-xl" />}

      {hasBriefing && (
        <Card>
          <CardContent className="pt-6">
            <Markdown>{b.markdown}</Markdown>
          </CardContent>
        </Card>
      )}

      <DebateCard />
    </div>
  )
}
