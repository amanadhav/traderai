import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, XAxis, YAxis } from 'recharts'
import { api, fmt$, fmtPct, clsPl } from '../api'
import { StatCard } from '@/components/stat-card'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

const activityChartConfig = {
  count: { label: 'Trades', color: 'var(--chart-2)' },
}

function ActivityMonitor({ trades }) {
  const now = new Date()
  const months = []
  for (let i = 5; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    months.push({
      key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      label: d.toLocaleString('en-US', { month: 'short' }),
      count: 0,
    })
  }
  const byKey = Object.fromEntries(months.map(m => [m.key, m]))
  for (const t of trades) {
    if (!t.date) continue
    const d = new Date(t.date)
    if (isNaN(d)) continue
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    if (byKey[key]) byKey[key].count += 1
  }

  // Most recent FULL month = previous calendar month (current month is partial)
  const lastFull = months[months.length - 2]
  const prior = months.slice(0, months.length - 2)
  const priorAvg = prior.length ? prior.reduce((s, m) => s + m.count, 0) / prior.length : null
  const overtrading = priorAvg != null && lastFull.count >= 6 && lastFull.count > 2 * priorAvg

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Activity Monitor - trades per month
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ChartContainer config={activityChartConfig} className="h-[140px] w-full">
          <BarChart data={months} margin={{ left: 4, right: 4, top: 4 }}>
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
            <YAxis hide allowDecimals={false} />
            <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
            <Bar dataKey="count" fill="var(--chart-2)" radius={4} />
          </BarChart>
        </ChartContainer>
        {overtrading ? (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-warn/30 text-warn">OVERTRADING?</Badge>
            <span className="text-sm">
              {lastFull.count} trades last month vs avg {priorAvg.toFixed(1)} - churn compounds into negative expectancy.
            </span>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Trade frequency normal.</p>
        )}
      </CardContent>
    </Card>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)}
      </div>
      <Skeleton className="h-[320px] rounded-xl" />
    </div>
  )
}

export default function Trades() {
  const tradesQ = useQuery({ queryKey: ['trades'], queryFn: api.trades })

  if (tradesQ.isLoading) return <LoadingSkeleton />
  if (tradesQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{tradesQ.error.message}</AlertDescription>
      </Alert>
    )
  }

  const trades = tradesQ.data ?? []
  const sorted = [...trades].reverse()
  const totalPL = trades.reduce((s, t) => s + (t.pl_dollar || 0), 0)
  const winners = trades.filter(t => (t.pl_dollar || 0) > 0)
  const winRate = trades.length ? (winners.length / trades.length * 100) : null
  const avgHold = trades.length ? trades.reduce((s, t) => s + (t.hold_days || 0), 0) / trades.length : null

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total Realized P&L"
          value={<span className={clsPl(totalPL)}>{fmt$(totalPL)}</span>}
          sub={`${trades.length} closed trades`}
        />
        <StatCard
          label="Win Rate"
          value={
            <span className={winRate > 50 ? 'text-gain' : winRate < 40 ? 'text-loss' : undefined}>
              {winRate != null ? winRate.toFixed(0) + '%' : '-'}
            </span>
          }
          sub={`${winners.length}W / ${trades.length - winners.length}L`}
        />
        <StatCard label="Avg Hold" value={avgHold != null ? avgHold.toFixed(0) + 'd' : '-'} />
        <StatCard
          label="Best Trade"
          value={
            <span className="text-gain">
              {trades.length ? fmt$(Math.max(...trades.map(t => t.pl_dollar || 0))) : '-'}
            </span>
          }
        />
      </div>

      <ActivityMonitor trades={trades} />

      <Card>
        <CardHeader>
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Trade Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          {trades.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No closed trades yet.
              <br />
              <span className="text-xs">
                Use <code className="font-mono">trading sell ACCT TICKER SHARES PRICE</code> to log trades.
              </span>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Acct</TableHead>
                  <TableHead>Ticker</TableHead>
                  <TableHead className="text-right">Shares</TableHead>
                  <TableHead className="text-right">Avg Cost</TableHead>
                  <TableHead className="text-right">Sell Price</TableHead>
                  <TableHead className="text-right">P&L $</TableHead>
                  <TableHead className="text-right">P&L %</TableHead>
                  <TableHead className="text-right">Hold</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((t, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-muted-foreground">{t.date}</TableCell>
                    <TableCell className="text-muted-foreground">{t.account}</TableCell>
                    <TableCell className="font-semibold">{t.ticker}</TableCell>
                    <TableCell className="tnum text-right">{t.shares}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(t.avg_cost)}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(t.sell_price)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(t.pl_dollar))}>{fmt$(t.pl_dollar)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(t.pl_pct))}>{fmtPct(t.pl_pct)}</TableCell>
                    <TableCell className="tnum text-right text-muted-foreground">
                      {t.hold_days != null ? t.hold_days + 'd' : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
