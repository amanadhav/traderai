import { Fragment, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { api, fmt$, fmtPct } from '../api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

const MAX_SCORE = 130

const SCORE_FACTORS = [
  ['RSI oversold (< 30 = 25, < 40 = 15)', 25],
  ['MACD histogram improving', 20],
  ['BB% oversold (< 20 = 20, < 40 = 10)', 20],
  ['Upside to 52W high (> 50% = 20)', 20],
  ['Volume surge (> 1.5x avg)', 10],
  ['Dividend yield (> 3% = 10)', 10],
  ['Relative strength vs SPY', 10],
  ['Near 52W low (< 10%)', 5],
  ['Analyst buy consensus', 5],
  ['Low short interest', 5],
]

function ScoreBar({ score }) {
  const pct = Math.min(100, Math.max(0, (score / MAX_SCORE) * 100))
  return (
    <div className="flex items-center gap-2">
      <Progress value={pct} className="h-1.5 flex-1" />
      <span className={cn(
        'tnum min-w-7 text-right text-xs font-semibold',
        score >= 80 ? 'text-gain' : score >= 60 ? 'text-warn' : 'text-loss'
      )}>
        {score}
      </span>
    </div>
  )
}

function ScoringFormula() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Scoring Formula ({MAX_SCORE} pts)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Factor</TableHead>
              <TableHead className="text-right">Max Pts</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {SCORE_FACTORS.map(([factor, pts]) => (
              <TableRow key={factor}>
                <TableCell className="text-xs">{factor}</TableCell>
                <TableCell className="tnum text-right font-semibold">{pts}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-[60px] rounded-xl" />
      <Skeleton className="h-[360px] rounded-xl" />
      <Skeleton className="h-[280px] rounded-xl" />
    </div>
  )
}

function RunScanCard({ status, onRun }) {
  const running = status?.running
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
        <div>
          <p className="text-sm font-medium">Universe Scanner</p>
          <p className="text-xs text-muted-foreground">
            {running
              ? `Scan running since ${status.started?.slice(11, 16)} - results appear here when done.`
              : 'Score the market through the entry algorithm and surface candidates.'}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={running} onClick={() => onRun(true)}>
            {running ? <Loader2 className="animate-spin" /> : null}
            Quick scan (~2-5 min)
          </Button>
          <Button size="sm" disabled={running} onClick={() => onRun(false)}>
            Full scan (~8-30 min)
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Scan() {
  const [filter, setFilter] = useState('all')
  const queryClient = useQueryClient()
  const scanQ = useQuery({ queryKey: ['scan-results'], queryFn: api.scanResults })
  const statusQ = useQuery({
    queryKey: ['scan-status'],
    queryFn: api.scanStatus,
    refetchInterval: (query) => (query.state.data?.running ? 5000 : false),
  })
  const wasRunning = useRef(false)
  useEffect(() => {
    const running = statusQ.data?.running
    if (wasRunning.current && running === false) {
      queryClient.invalidateQueries({ queryKey: ['scan-results'] })
      if (statusQ.data?.returncode === 0) toast.success('Scan complete - results updated')
      else toast.error('Scan failed - check the server logs')
    }
    wasRunning.current = !!running
  }, [statusQ.data?.running, statusQ.data?.returncode, queryClient])

  async function handleRun(quick) {
    try {
      await api.scanRun({ quick })
      await statusQ.refetch()
      toast.success(`${quick ? 'Quick' : 'Full'} scan started`)
    } catch (e) {
      toast.error(e.message)
    }
  }

  const explainQ = useQuery({
    queryKey: ['scan-explanations'],
    queryFn: api.scanExplanations,
    enabled: false,
    staleTime: Infinity,
  })

  async function handleExplain() {
    const { data, error } = await explainQ.refetch()
    if (error) {
      toast.error(error.message)
    } else if (data && data.available === false) {
      toast.error(data.reason || 'Explanations unavailable.')
    }
  }

  if (scanQ.isLoading) return <LoadingSkeleton />
  if (scanQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>Error loading scan results: {scanQ.error.message}</AlertDescription>
      </Alert>
    )
  }

  const data = scanQ.data
  if (!data?.available) {
    return (
      <div className="space-y-4">
        <RunScanCard status={statusQ.data} onRun={handleRun} />
        <Card>
          <CardContent className="py-6 text-center text-sm text-muted-foreground">
            {statusQ.data?.running
              ? 'Scanning the universe… this page updates automatically when it finishes.'
              : 'No scan results yet - run your first scan above.'}
          </CardContent>
        </Card>
      </div>
    )
  }

  const candidates = data.candidates || []
  const filtered = filter === 'all' ? candidates :
                   filter === 'strong' ? candidates.filter(c => c.score >= 80) :
                   candidates.filter(c => c.score >= 60 && c.score < 80)

  const explanations = explainQ.data?.available ? (explainQ.data.explanations || {}) : {}

  return (
    <div className="space-y-4">
      <RunScanCard status={statusQ.data} onRun={handleRun} />
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span>
          {data.scan_time ? `Last run: ${new Date(data.scan_time).toLocaleString()}` : ''}
          {data.tickers_scanned ? ` · ${data.tickers_scanned} tickers scanned` : ''}
        </span>
        {data.market && (
          <span className="ml-auto flex gap-4">
            <span>VIX <span className={cn('tnum font-semibold', data.market.vix > 25 ? 'text-loss' : 'text-gain')}>{data.market.vix?.toFixed(1)}</span></span>
            <span>SPY RSI <span className="tnum font-semibold text-foreground">{data.market.spy_rsi?.toFixed(1)}</span></span>
            <span>QQQ RSI <span className="tnum font-semibold text-foreground">{data.market.qqq_rsi?.toFixed(1)}</span></span>
          </span>
        )}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <Tabs value={filter} onValueChange={setFilter}>
            <TabsList>
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="strong">Strong (80+)</TabsTrigger>
              <TabsTrigger value="ok">OK (60-79)</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="flex items-center gap-3">
            {explainQ.data?.available && explainQ.data.cached && (
              <Badge variant="outline" className="text-[10px] font-normal text-muted-foreground">cached</Badge>
            )}
            <Button variant="outline" size="sm" onClick={handleExplain} disabled={explainQ.isFetching}>
              {explainQ.isFetching
                ? <Loader2 className="animate-spin" />
                : <Sparkles />}
              Explain with AI
            </Button>
            <span className="text-xs text-muted-foreground">{filtered.length} results</span>
          </div>
        </CardHeader>
        <CardContent>
          {filtered.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No results match filter.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">#</TableHead>
                  <TableHead>Ticker</TableHead>
                  <TableHead className="min-w-[140px]">Score</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="text-right">RSI</TableHead>
                  <TableHead className="text-right">BB%</TableHead>
                  <TableHead className="text-right">Day%</TableHead>
                  <TableHead className="text-right">Upside</TableHead>
                  <TableHead>Sector</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((c, i) => (
                  <Fragment key={c.ticker}>
                  <TableRow className={cn(explanations[c.ticker] && 'border-b-0')}>
                    <TableCell className="tnum text-xs text-muted-foreground">{i + 1}</TableCell>
                    <TableCell className="font-semibold">{c.ticker}</TableCell>
                    <TableCell><ScoreBar score={c.score} /></TableCell>
                    <TableCell className="tnum text-right">{c.price ? fmt$(c.price) : '-'}</TableCell>
                    <TableCell className={cn('tnum text-right', c.rsi > 70 ? 'text-loss' : c.rsi < 35 ? 'text-gain' : '')}>
                      {c.rsi?.toFixed(1) ?? '-'}
                    </TableCell>
                    <TableCell className={cn('tnum text-right', c.bb_pct < 20 ? 'text-gain' : c.bb_pct > 80 ? 'text-loss' : '')}>
                      {c.bb_pct != null ? `${c.bb_pct.toFixed(0)}%` : '-'}
                    </TableCell>
                    <TableCell className={cn('tnum text-right', c.change_pct >= 0 ? 'text-gain' : 'text-loss')}>
                      {c.change_pct != null ? fmtPct(c.change_pct) : '-'}
                    </TableCell>
                    <TableCell className="tnum text-right text-gain">
                      {c.upside_pct != null ? `+${c.upside_pct.toFixed(1)}%` : '-'}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{c.sector || '-'}</TableCell>
                  </TableRow>
                  {explanations[c.ticker] && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell />
                      <TableCell colSpan={8} className="pt-0 text-xs italic text-muted-foreground">
                        {explanations[c.ticker]}
                      </TableCell>
                    </TableRow>
                  )}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ScoringFormula />
    </div>
  )
}
