import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Area, AreaChart, XAxis, YAxis } from 'recharts'
import { CheckCircle2 } from 'lucide-react'
import { api, fmt$, fmtPct, clsPl } from '../api'
import { configApi } from '@/lib/config-api'
import { StatCard } from '@/components/stat-card'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { TickerChartDialog } from '@/components/ticker-chart'
import { cn } from '@/lib/utils'

export const TYPE_BADGES = {
  L: 'Long', S: 'Swing', I: 'Income', Lifetime: 'Lifetime', Spec: 'Spec',
}

export function TypeBadge({ type }) {
  return <Badge variant="secondary" className="font-normal">{TYPE_BADGES[type] ?? type}</Badge>
}

function accountValue(acct, prices) {
  let val = acct.cash || 0
  for (const p of (acct.positions || [])) {
    const price = prices[p.ticker]?.price ?? p.avg_cost
    val += price * p.shares
  }
  return val
}

const equityChartConfig = {
  total: { label: 'Total', color: 'var(--chart-1)' },
}

function EquityCurve({ history }) {
  if (!history?.length) return null
  const data = history.slice(-90)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Equity Curve - last {data.length} sessions
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ChartContainer config={equityChartConfig} className="h-[180px] w-full">
          <AreaChart data={data} margin={{ left: 4, right: 4, top: 4 }}>
            <defs>
              <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.25} />
                <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" hide />
            <YAxis domain={['auto', 'auto']} hide />
            <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
            <Area
              dataKey="total" type="monotone" strokeWidth={1.5}
              stroke="var(--chart-1)" fill="url(#equityFill)"
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

function MacroStat({ label, value, valueClass, badge }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn('tnum mt-0.5 flex items-center gap-1.5 text-sm font-semibold', valueClass)}>
        {value}
        {badge}
      </div>
    </div>
  )
}

function MacroRegimeCard() {
  const macroQ = useQuery({ queryKey: ['macro'], queryFn: api.macro, staleTime: 600_000 })
  const m = macroQ.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Macro Regime
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {macroQ.error ? (
          <p className="text-sm text-muted-foreground">Could not load macro data: {macroQ.error.message}</p>
        ) : !m ? (
          <Skeleton className="h-10 w-full" />
        ) : (
          <>
            <div className="flex flex-wrap gap-x-8 gap-y-3">
              {m.yield_10y != null && <MacroStat label="10Y Yield" value={`${m.yield_10y.toFixed(2)}%`} />}
              {m.yield_3m != null && <MacroStat label="3M Yield" value={`${m.yield_3m.toFixed(2)}%`} />}
              {m.curve_spread_10y_3m != null && (
                <MacroStat
                  label="Curve 10Y-3M"
                  value={`${m.curve_spread_10y_3m >= 0 ? '+' : ''}${m.curve_spread_10y_3m.toFixed(2)}%`}
                  valueClass={m.curve_inverted ? 'text-loss' : 'text-gain'}
                  badge={m.curve_inverted && (
                    <Badge variant="destructive" className="px-1.5 py-0 text-[10px]">INVERTED</Badge>
                  )}
                />
              )}
              {m.cpi_yoy != null && <MacroStat label="CPI YoY" value={`${m.cpi_yoy.toFixed(1)}%`} />}
              {m.fed_funds != null && <MacroStat label="Fed Funds" value={`${m.fed_funds.toFixed(2)}%`} />}
              {m.unemployment != null && <MacroStat label="Unemployment" value={`${m.unemployment.toFixed(1)}%`} />}
            </div>
            {m.fred_available === false && (
              <p className="text-xs text-muted-foreground">
                Add a free FRED_API_KEY to .env for CPI/Fed/unemployment
              </p>
            )}
            {m.regime_note && <p className="text-xs text-muted-foreground">{m.regime_note}</p>}
          </>
        )}
      </CardContent>
    </Card>
  )
}

const SEVERITY_ORDER = { URGENT: 0, WARN: 1 }

function GuardianCard() {
  const guardianQ = useQuery({ queryKey: ['guardian'], queryFn: api.guardian, staleTime: 300_000 })

  const violations = [...(guardianQ.data?.violations ?? [])]
    .sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Discipline Guardian
        </CardTitle>
      </CardHeader>
      <CardContent>
        {guardianQ.error ? (
          <p className="text-sm text-muted-foreground">Could not load guardian: {guardianQ.error.message}</p>
        ) : !guardianQ.data ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : violations.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <CheckCircle2 className="size-4" />
            All rules respected - no violations.
          </p>
        ) : (
          <div className="space-y-2">
            {violations.map((v, i) => (
              <div key={i} className="flex items-start gap-2">
                <Badge
                  variant={v.severity === 'URGENT' ? 'destructive' : 'outline'}
                  className={cn(v.severity !== 'URGENT' && 'border-warn/30 text-warn')}
                >
                  {v.severity}
                </Badge>
                <p className="text-sm">
                  {v.ticker && <span className="font-semibold">{v.ticker} - </span>}
                  {v.message}
                </p>
              </div>
            ))}
          </div>
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
      <Skeleton className="h-[240px] rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-[280px] rounded-xl" />
        <Skeleton className="h-[280px] rounded-xl" />
      </div>
    </div>
  )
}

function Greeting() {
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: configApi.get })
  const name = config?.profile?.name?.trim().split(/\s+/)[0]
  const hour = new Date().getHours()
  const timeOfDay = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric',
  })
  return (
    <div className="pb-1">
      <h2 className="text-xl font-semibold tracking-tight">
        {timeOfDay}{name ? `, ${name}` : ''}
      </h2>
      <p className="text-xs text-muted-foreground">{today}</p>
    </div>
  )
}

export default function Dashboard() {
  const [chartTicker, setChartTicker] = useState(null)
  const positionsQ = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const pricesQ = useQuery({ queryKey: ['prices'], queryFn: api.prices, refetchInterval: 120_000 })
  const historyQ = useQuery({ queryKey: ['history'], queryFn: api.history })

  if (positionsQ.isLoading || pricesQ.isLoading) return <LoadingSkeleton />
  if (positionsQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>Could not load portfolio: {positionsQ.error.message}</AlertDescription>
      </Alert>
    )
  }

  const accounts = positionsQ.data.accounts ?? {}
  const prices = pricesQ.data ?? {}
  const history = historyQ.data ?? []

  const accountEntries = Object.entries(accounts)
  const accountValues = accountEntries.map(([name, a]) => ({
    name, cash: a.cash ?? 0, value: accountValue(a, prices),
  }))
  const total = accountValues.reduce((sum, a) => sum + a.value, 0)

  if (accountEntries.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <p className="font-medium">Welcome to TraderAI</p>
          <p className="mt-1 text-sm text-muted-foreground">
            No portfolio yet. Run the setup wizard to add your accounts, cash, and holdings.
          </p>
          <Button className="mt-4" onClick={() => (window.location.href = '/setup')}>
            Open setup
          </Button>
        </CardContent>
      </Card>
    )
  }

  const prevTotal = history.length >= 2 ? history[history.length - 2].total : null
  const dayChange = prevTotal ? total - prevTotal : null

  const allPositions = []
  for (const [acct, a] of Object.entries(accounts)) {
    for (const p of (a.positions || [])) {
      const snap = prices[p.ticker] || {}
      const price = snap.price ?? p.avg_cost
      const pl = (price - p.avg_cost) * p.shares
      const plPct = (price - p.avg_cost) / p.avg_cost * 100
      allPositions.push({ ...p, acct, price, pl, plPct, snap })
    }
  }

  const topMovers = [...allPositions]
    .filter(p => p.snap.change_pct != null)
    .sort((a, b) => Math.abs(b.snap.change_pct) - Math.abs(a.snap.change_pct))
    .slice(0, 6)

  const byValue = [...allPositions]
    .sort((a, b) => b.price * b.shares - a.price * a.shares)
    .slice(0, 8)

  return (
    <div className="space-y-4">
      <Greeting />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total Portfolio"
          value={fmt$(total)}
          sub={dayChange != null ? `${fmtPct(dayChange / (total - dayChange) * 100)} today (${fmt$(dayChange)})` : 'no prior snapshot'}
          subClass={dayChange != null ? clsPl(dayChange) : undefined}
        />
        {accountValues.slice(0, 2).map(a => (
          <StatCard key={a.name} label={a.name.replace(/_/g, ' ')} value={fmt$(a.value)} sub={`Cash ${fmt$(a.cash)}`} />
        ))}
        <StatCard
          label="Positions"
          value={allPositions.length}
          sub={`across ${Object.keys(accounts).length} accounts`}
        />
      </div>

      <MacroRegimeCard />
      <GuardianCard />

      <EquityCurve history={history} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Today's Movers
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Acct</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead className="text-right">Day</TableHead>
                  <TableHead className="text-right">P&L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {topMovers.map(p => (
                  <TableRow key={p.ticker + p.acct}>
                    <TableCell className="font-semibold">
                      <button type="button" className="font-semibold hover:underline" onClick={() => setChartTicker(p.ticker)}>
                        {p.ticker}
                      </button>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{p.acct}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(p.price)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(p.snap.change_pct))}>{fmtPct(p.snap.change_pct)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(p.pl))}>{fmt$(p.pl)}</TableCell>
                  </TableRow>
                ))}
                {topMovers.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      No live price data
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Portfolio Breakdown
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Acct</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="text-right">Total P&L</TableHead>
                  <TableHead>Type</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {byValue.map(p => (
                  <TableRow key={p.ticker + p.acct}>
                    <TableCell className="font-semibold">
                      <button type="button" className="font-semibold hover:underline" onClick={() => setChartTicker(p.ticker)}>
                        {p.ticker}
                      </button>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{p.acct}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(p.price * p.shares)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(p.pl))}>{fmt$(p.pl)}</TableCell>
                    <TableCell><TypeBadge type={p.type} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {positionsQ.data.watchlist?.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Watchlist
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {positionsQ.data.watchlist.map(t => (
              <Badge key={typeof t === 'string' ? t : t.ticker} variant="outline" className="font-normal">
                {typeof t === 'string' ? t : t.ticker}
              </Badge>
            ))}
          </CardContent>
        </Card>
      )}

      {chartTicker && (
        <TickerChartDialog ticker={chartTicker} open onClose={() => setChartTicker(null)} />
      )}
    </div>
  )
}
