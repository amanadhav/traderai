import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ComposedChart, Line, LineChart, ReferenceLine, XAxis, YAxis } from 'recharts'
import { api, fmt$ } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ChartContainer, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { cn } from '@/lib/utils'

const RANGES = [
  { label: '90D', days: 90 },
  { label: '180D', days: 180 },
  { label: '1Y', days: 365 },
]

const priceChartConfig = {
  close: { label: 'Close', color: 'var(--chart-1)' },
  ma50: { label: 'MA50', color: 'var(--chart-3)' },
  ma200: { label: 'MA200', color: 'var(--chart-4)' },
}

const rsiChartConfig = {
  rsi: { label: 'RSI', color: 'var(--chart-2)' },
}

function SetupStat({ label, value, sub, valueClass }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className={cn('tnum text-sm font-semibold', valueClass)}>{value}</div>
      {sub != null && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}

function TradeSetup({ ticker }) {
  const [equity, setEquity] = useState('10000')
  const [requested, setRequested] = useState(null) // equity value the user asked to compute with

  const setupQ = useQuery({
    queryKey: ['trade-setup', ticker, requested],
    queryFn: () => api.tradeSetup(ticker, requested),
    enabled: requested != null,
  })
  const s = setupQ.data

  return (
    <div className="space-y-3 border-t pt-4">
      <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Trade Setup</div>
      <div className="flex items-center gap-2">
        <Input
          type="number" min="0" step="any" value={equity}
          onChange={e => setEquity(e.target.value)}
          className="tnum h-8 w-32"
          aria-label="Account equity"
        />
        <Button
          variant="outline" size="sm"
          disabled={setupQ.isFetching}
          onClick={() => setRequested(+equity > 0 ? +equity : 10000)}
        >
          {setupQ.isFetching ? 'Computing…' : 'Compute setup'}
        </Button>
      </div>
      {setupQ.error && (
        <Alert variant="destructive">
          <AlertDescription>{setupQ.error.message}</AlertDescription>
        </Alert>
      )}
      {s && (
        <div className="grid grid-cols-3 gap-x-4 gap-y-3 sm:grid-cols-4">
          <SetupStat label="Entry" value={fmt$(s.entry)} />
          <SetupStat label="Stop" value={fmt$(s.stop)} sub={s.stop_basis} />
          <SetupStat label="Target" value={fmt$(s.target)} />
          <SetupStat label="R:R" value={s.reward_risk != null ? `${s.reward_risk.toFixed(2)}:1` : '-'} />
          <SetupStat label="Shares" value={s.shares} sub={s.position_value != null ? fmt$(s.position_value) : undefined} />
          <SetupStat label="$ Risk" value={fmt$(s.dollar_risk)} valueClass="text-loss" />
          <SetupStat label="$ Reward" value={fmt$(s.dollar_reward)} valueClass="text-gain" />
          <SetupStat label="ATR" value={s.atr != null ? s.atr.toFixed(2) : '-'} sub={s.atr_pct != null ? `${s.atr_pct.toFixed(1)}%` : undefined} />
        </div>
      )}
      {s?.rules_applied?.length > 0 && (
        <div className="text-xs text-muted-foreground">{s.rules_applied.join(' · ')}</div>
      )}
    </div>
  )
}

export function TickerChartDialog({ ticker, open, onClose }) {
  const [days, setDays] = useState(180)

  const chartQ = useQuery({
    queryKey: ['chart', ticker, days],
    queryFn: () => api.chart(ticker, days),
    enabled: Boolean(open && ticker),
  })

  const d = chartQ.data
  const data = d
    ? d.dates.map((date, i) => ({
        date,
        close: d.close[i],
        ma50: d.ma50?.[i],
        ma200: d.ma200?.[i],
        rsi: d.rsi?.[i],
      }))
    : []
  const stop = d?.stop

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{ticker}</DialogTitle>
        </DialogHeader>

        <div className="flex gap-1">
          {RANGES.map(r => (
            <Button
              key={r.days}
              variant="outline"
              size="sm"
              className={cn(days === r.days && 'bg-accent')}
              onClick={() => setDays(r.days)}
            >
              {r.label}
            </Button>
          ))}
        </div>

        {chartQ.isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-[260px] rounded-xl" />
            <Skeleton className="h-[80px] rounded-xl" />
          </div>
        )}

        {chartQ.error && (
          <Alert variant="destructive">
            <AlertDescription>Could not load chart: {chartQ.error.message}</AlertDescription>
          </Alert>
        )}

        {d && (
          <div className="space-y-2">
            <ChartContainer config={priceChartConfig} className="h-[260px] w-full">
              <ComposedChart data={data} margin={{ left: 4, right: 4, top: 4 }}>
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                  tickCount={5}
                  minTickGap={60}
                />
                <YAxis domain={['auto', 'auto']} width={50} tickLine={false} axisLine={false} />
                <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                {stop != null && (
                  <ReferenceLine
                    y={stop}
                    stroke="var(--loss)"
                    strokeDasharray="4 4"
                    label={{ value: 'Stop', position: 'insideBottomLeft', fill: 'var(--loss)', fontSize: 10 }}
                  />
                )}
                <Line dataKey="close" type="monotone" stroke="var(--chart-1)" strokeWidth={1.5} dot={false} connectNulls />
                <Line dataKey="ma50" type="monotone" stroke="var(--chart-3)" strokeWidth={1} strokeDasharray="4 3" dot={false} connectNulls />
                <Line dataKey="ma200" type="monotone" stroke="var(--chart-4)" strokeWidth={1} strokeDasharray="4 3" dot={false} connectNulls />
              </ComposedChart>
            </ChartContainer>

            <ChartContainer config={rsiChartConfig} className="h-[80px] w-full">
              <LineChart data={data} margin={{ left: 4, right: 4, top: 4 }}>
                <XAxis dataKey="date" hide />
                <YAxis domain={[0, 100]} width={50} tickLine={false} axisLine={false} ticks={[30, 70]} />
                <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
                <ReferenceLine y={70} stroke="var(--muted-foreground)" strokeDasharray="2 4" strokeOpacity={0.5} />
                <ReferenceLine y={30} stroke="var(--muted-foreground)" strokeDasharray="2 4" strokeOpacity={0.5} />
                <Line dataKey="rsi" type="monotone" stroke="var(--chart-2)" strokeWidth={1} dot={false} connectNulls />
              </LineChart>
            </ChartContainer>
          </div>
        )}

        <TradeSetup key={ticker} ticker={ticker} />
      </DialogContent>
    </Dialog>
  )
}
