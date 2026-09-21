import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bar, BarChart, XAxis, YAxis } from 'recharts'
import { FlaskConical, Loader2, Play } from 'lucide-react'
import { toast } from 'sonner'
import { api, fmtPct, clsPl } from '../api'
import { StatCard } from '@/components/stat-card'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

const alphaChartConfig = {
  median_alpha: { label: 'Median Alpha %', color: 'var(--chart-1)' },
}

function fmtNum(n, digits = 2) {
  if (n == null) return '-'
  return n.toFixed(digits)
}

function RunCard({ status, statusFetched }) {
  const [lookback, setLookback] = useState('365')
  const [hold, setHold] = useState('60')
  const [full, setFull] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const queryClient = useQueryClient()

  const running = status?.running === true

  async function run(e) {
    e.preventDefault()
    setSubmitting(true)
    try {
      const res = await api.backtestRun({
        lookback: Number(lookback) || 365,
        hold: Number(hold) || 60,
        full,
      })
      toast.success(res.message || 'Backtest started')
      queryClient.invalidateQueries({ queryKey: ['backtest-status'] })
    } catch (err) {
      toast.error(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          <FlaskConical className="size-3.5" /> Run Backtest
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={run} className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <Label htmlFor="bt-lookback" className="text-xs text-muted-foreground">Lookback days</Label>
            <Input
              id="bt-lookback" type="number" min="30" max="3650" className="w-28"
              value={lookback} onChange={e => setLookback(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="bt-hold" className="text-xs text-muted-foreground">Hold days</Label>
            <Input
              id="bt-hold" type="number" min="5" max="365" className="w-28"
              value={hold} onChange={e => setHold(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 pb-2">
            <Switch id="bt-full" checked={full} onCheckedChange={setFull} />
            <Label htmlFor="bt-full" className="text-xs text-muted-foreground">
              Full universe (~350 tickers, slow)
            </Label>
          </div>
          <Button type="submit" disabled={submitting || running || !statusFetched}>
            {running ? <Loader2 className="animate-spin" /> : <Play />}
            {running ? 'Running…' : 'Run'}
          </Button>
          {running && (
            <span className="pb-2 text-xs text-muted-foreground">
              Backtest running{status?.started ? ` - started ${status.started}` : ''}. Polling every 5s.
            </span>
          )}
        </form>
      </CardContent>
    </Card>
  )
}

function TierTable({ tiers }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Tier Performance
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Threshold</TableHead>
              <TableHead className="text-right">N</TableHead>
              <TableHead className="text-right">Win %</TableHead>
              <TableHead className="text-right">Avg Return</TableHead>
              <TableHead className="text-right">Avg Alpha</TableHead>
              <TableHead className="text-right">Median Alpha</TableHead>
              <TableHead className="text-right">Best</TableHead>
              <TableHead className="text-right">Worst</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tiers.map(t => (
              <TableRow key={t.threshold}>
                <TableCell className="font-semibold">
                  ≥{t.threshold}
                  {t.live_equiv && <span className="ml-1.5 font-normal text-muted-foreground">({t.live_equiv})</span>}
                </TableCell>
                <TableCell className="tnum text-right">{t.n_entries}</TableCell>
                <TableCell className="tnum text-right">{fmtNum(t.win_rate, 1)}%</TableCell>
                <TableCell className="tnum text-right">{fmtPct(t.avg_return)}</TableCell>
                <TableCell className={cn('tnum text-right', clsPl(t.avg_alpha))}>{fmtPct(t.avg_alpha)}</TableCell>
                <TableCell className={cn('tnum text-right', clsPl(t.median_alpha))}>{fmtPct(t.median_alpha)}</TableCell>
                <TableCell className={cn('tnum text-right', clsPl(t.best_alpha))}>{fmtPct(t.best_alpha)}</TableCell>
                <TableCell className={cn('tnum text-right', clsPl(t.worst_alpha))}>{fmtPct(t.worst_alpha)}</TableCell>
              </TableRow>
            ))}
            {tiers.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                  No tier data
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function AlphaChart({ tiers }) {
  const data = tiers.map(t => ({ threshold: `≥${t.threshold}`, median_alpha: t.median_alpha }))
  if (!data.length) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Alpha by Score - median alpha per tier
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={alphaChartConfig} className="h-[180px] w-full">
          <BarChart data={data} margin={{ left: 4, right: 4, top: 4 }}>
            <XAxis dataKey="threshold" tickLine={false} axisLine={false} />
            <YAxis domain={['auto', 'auto']} hide />
            <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
            <Bar dataKey="median_alpha" fill="var(--chart-1)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

function EntriesTable({ entries }) {
  const rows = entries.slice(0, 30)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Sample Entries - first {rows.length} of {entries.length}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Ticker</TableHead>
              <TableHead>Entry Date</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead className="text-right">Return</TableHead>
              <TableHead className="text-right">Alpha</TableHead>
              <TableHead>Result</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((e, i) => (
              <TableRow key={`${e.ticker}-${e.entry_date}-${i}`}>
                <TableCell className="font-semibold">{e.ticker}</TableCell>
                <TableCell className="text-muted-foreground">{e.entry_date}</TableCell>
                <TableCell className="tnum text-right">{e.tech_score}</TableCell>
                <TableCell className="tnum text-right">{fmtPct(e.return_pct)}</TableCell>
                <TableCell className={cn('tnum text-right', clsPl(e.alpha))}>{fmtPct(e.alpha)}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={cn('font-normal', e.win ? 'text-gain' : 'text-loss')}>
                    {e.win ? 'Win' : 'Loss'}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                  No entries recorded
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

export default function Backtest() {
  const queryClient = useQueryClient()

  const statusQ = useQuery({
    queryKey: ['backtest-status'],
    queryFn: api.backtestStatus,
    // poll every 5s only while a run is in progress
    refetchInterval: (query) => (query.state.data?.running ? 5000 : false),
  })
  const running = statusQ.data?.running === true

  const resultsQ = useQuery({
    queryKey: ['backtest-results'],
    queryFn: api.backtestResults,
  })

  // When a run finishes (running flips true -> false), refresh results + toast
  const prevRunning = useRef(false)
  useEffect(() => {
    if (prevRunning.current && !running && statusQ.data) {
      queryClient.invalidateQueries({ queryKey: ['backtest-results'] })
      if (statusQ.data.returncode === 0) {
        toast.success('Backtest finished - results updated')
      } else {
        toast.error(`Backtest exited with code ${statusQ.data.returncode ?? '?'}`)
      }
    }
    prevRunning.current = running
  }, [running, statusQ.data, queryClient])

  const results = resultsQ.data
  const tiers = results?.available ? (results.tiers ?? []) : []
  const populated = tiers.filter(t => (t.n_entries ?? 0) > 0)
  const bestTier = populated.length
    ? populated.reduce((best, t) => ((t.median_alpha ?? -Infinity) > (best.median_alpha ?? -Infinity) ? t : best), populated[0])
    : null

  return (
    <div className="space-y-4">
      <RunCard status={statusQ.data} statusFetched={!statusQ.isLoading} />

      {resultsQ.isLoading && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)}
          </div>
          <Skeleton className="h-[280px] rounded-xl" />
        </>
      )}

      {resultsQ.error && (
        <Alert variant="destructive">
          <AlertDescription>Could not load backtest results: {resultsQ.error.message}</AlertDescription>
        </Alert>
      )}

      {results && !results.available && (
        <Alert>
          <AlertDescription className="text-muted-foreground">
            {results.message || 'No backtest results available yet. Run a backtest to generate them.'}
          </AlertDescription>
        </Alert>
      )}

      {results?.available && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Total Entries"
              value={results.n_entries_total ?? '-'}
              sub={results.lookback_days ? `${results.lookback_days}d lookback · ${results.hold_days}d hold` : results.generated}
            />
            <StatCard
              label="SPY Baseline Win Rate"
              value={results.spy_baseline?.win_rate != null ? `${fmtNum(results.spy_baseline.win_rate, 1)}%` : '-'}
              sub={results.spy_baseline?.avg_return != null ? `avg return ${fmtPct(results.spy_baseline.avg_return)}` : undefined}
            />
            <StatCard
              label="Best Tier Median Alpha"
              value={bestTier ? fmtPct(bestTier.median_alpha) : '-'}
              subClass={bestTier ? clsPl(bestTier.median_alpha) : undefined}
              sub={bestTier ? `${bestTier.n_entries} entries` : undefined}
            />
            <StatCard
              label="Best Tier Threshold"
              value={bestTier ? `≥${bestTier.threshold}` : '-'}
              sub={bestTier?.live_equiv}
            />
          </div>

          <TierTable tiers={tiers} />
          <AlphaChart tiers={tiers} />
          <EntriesTable entries={results.all_entries ?? []} />
        </>
      )}
    </div>
  )
}
