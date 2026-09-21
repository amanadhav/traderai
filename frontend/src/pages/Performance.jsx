import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts'
import { api, fmt$, fmtPct, clsPl } from '../api'
import { StatCard } from '@/components/stat-card'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent,
} from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

const perfChartConfig = {
  total: { label: 'Total', color: 'var(--chart-1)' },
  roth: { label: 'ROTH', color: 'var(--chart-2)' },
  tod: { label: 'TOD', color: 'var(--chart-3)' },
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)}
      </div>
      <Skeleton className="h-[360px] rounded-xl" />
      <Skeleton className="h-[280px] rounded-xl" />
    </div>
  )
}

export default function Performance() {
  const historyQ = useQuery({ queryKey: ['history'], queryFn: api.history })

  if (historyQ.isLoading) return <LoadingSkeleton />
  if (historyQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{historyQ.error.message}</AlertDescription>
      </Alert>
    )
  }

  const history = historyQ.data ?? []

  const chartData = history.map(h => ({
    date: h.date,
    total: h.total,
    roth: h.roth,
    tod: h.tod,
  }))

  const first = history[0]
  const last = history[history.length - 1]
  const totalReturn = first && last ? ((last.total - first.total) / first.total * 100) : null
  const totalPL = first && last ? last.total - first.total : null
  const peak = history.reduce((m, h) => Math.max(m, h.total), 0)
  const maxDD = history.reduce((dd, h) => {
    const drawdown = (h.total - peak) / peak * 100
    return Math.min(dd, drawdown)
  }, 0)

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Current Value"
          value={last ? fmt$(last.total) : '-'}
          sub={`${history.length} days tracked`}
        />
        <StatCard
          label="Total Return"
          value={<span className={clsPl(totalReturn)}>{totalReturn != null ? fmtPct(totalReturn) : '-'}</span>}
          sub={totalPL != null ? fmt$(totalPL) : '-'}
          subClass={clsPl(totalPL)}
        />
        <StatCard label="Peak Value" value={fmt$(peak)} />
        <StatCard
          label="Max Drawdown"
          value={<span className={maxDD < -10 ? 'text-loss' : undefined}>{fmtPct(maxDD)}</span>}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Equity Curve
          </CardTitle>
        </CardHeader>
        <CardContent>
          {chartData.length < 2 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              Need at least 2 days of data for chart.
              <br />
              <span className="text-xs">
                Run <code className="font-mono">python morning_run.py</code> each day to build history.
              </span>
            </div>
          ) : (
            <ChartContainer config={perfChartConfig} className="h-[300px] w-full">
              <AreaChart data={chartData} margin={{ left: 4, right: 4, top: 4 }}>
                <defs>
                  <linearGradient id="perfTotalFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                <YAxis
                  domain={['auto', 'auto']}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11 }}
                  tickFormatter={v => '$' + (v / 1000).toFixed(0) + 'k'}
                  width={48}
                />
                <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                <ChartLegend content={<ChartLegendContent />} />
                <Area
                  dataKey="total" type="monotone" strokeWidth={2}
                  stroke="var(--chart-1)" fill="url(#perfTotalFill)"
                />
                <Area
                  dataKey="roth" type="monotone" strokeWidth={1.5} strokeDasharray="4 2"
                  stroke="var(--chart-2)" fill="transparent"
                />
                <Area
                  dataKey="tod" type="monotone" strokeWidth={1.5} strokeDasharray="4 2"
                  stroke="var(--chart-3)" fill="transparent"
                />
              </AreaChart>
            </ChartContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            History Log
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Date</TableHead>
                <TableHead className="text-right">ROTH</TableHead>
                <TableHead className="text-right">TOD</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead className="text-right">Day Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...history].reverse().map((h, i, arr) => {
                const prev = arr[i + 1]
                const dayChange = prev ? h.total - prev.total : null
                return (
                  <TableRow key={h.date}>
                    <TableCell className="text-muted-foreground">{h.date}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(h.roth)}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(h.tod)}</TableCell>
                    <TableCell className="tnum text-right font-semibold">{fmt$(h.total)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(dayChange))}>
                      {dayChange != null
                        ? `${dayChange >= 0 ? '+' : ''}${fmt$(dayChange)} (${fmtPct(dayChange / (h.total - dayChange) * 100)})`
                        : '-'}
                    </TableCell>
                  </TableRow>
                )
              })}
              {history.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    No history yet
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
