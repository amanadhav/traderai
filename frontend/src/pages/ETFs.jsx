import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api, fmt$, fmtPct, clsPl } from '../api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

function rsiSignal(rsi) {
  if (rsi == null) return { label: '-', cls: 'text-muted-foreground' }
  if (rsi < 30) return { label: 'Oversold', cls: 'text-gain' }
  if (rsi < 40) return { label: 'OK entry', cls: 'text-gain' }
  if (rsi > 75) return { label: 'Overbought', cls: 'text-loss' }
  if (rsi > 65) return { label: 'Extended', cls: 'text-warn' }
  return { label: 'Neutral', cls: 'text-muted-foreground' }
}

export default function ETFs() {
  const etfsQ = useQuery({
    queryKey: ['etfs'],
    queryFn: api.etfs,
    staleTime: 10 * 60_000,
  })

  if (etfsQ.isLoading) return <Skeleton className="h-[400px] rounded-xl" />
  if (etfsQ.error) {
    return <Alert variant="destructive"><AlertDescription>{etfsQ.error.message}</AlertDescription></Alert>
  }

  const etfs = etfsQ.data?.etfs ?? []

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              ETF Watchlist - live technicals
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Edit the list in Settings → Narratives. Score any ETF with{' '}
              <code className="rounded bg-muted px-1 text-[11px]">python etf_score.py TICKER</code>.
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => etfsQ.refetch()} disabled={etfsQ.isFetching}>
            <RefreshCw className={etfsQ.isFetching ? 'animate-spin' : ''} /> Refresh
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Day</TableHead>
                <TableHead className="text-right">RSI</TableHead>
                <TableHead className="text-right">BB%</TableHead>
                <TableHead className="text-right">vs 52W low</TableHead>
                <TableHead>Signal</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {etfs.map(e => {
                const sig = rsiSignal(e.rsi)
                return (
                  <TableRow key={e.ticker}>
                    <TableCell className="font-semibold">{e.ticker}</TableCell>
                    <TableCell className="tnum text-right">{fmt$(e.price)}</TableCell>
                    <TableCell className={cn('tnum text-right', clsPl(e.pct_chg_today))}>
                      {fmtPct(e.pct_chg_today)}
                    </TableCell>
                    <TableCell className={cn('tnum text-right', sig.cls)}>
                      {e.rsi != null ? e.rsi.toFixed(1) : '-'}
                    </TableCell>
                    <TableCell className="tnum text-right">
                      {e.bb_pct != null ? e.bb_pct.toFixed(0) : '-'}
                    </TableCell>
                    <TableCell className="tnum text-right">
                      {e.pct_from_52w_low != null ? `+${e.pct_from_52w_low.toFixed(0)}%` : '-'}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={cn('font-normal', sig.cls)}>{sig.label}</Badge>
                    </TableCell>
                  </TableRow>
                )
              })}
              {etfs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                    Watchlist empty - add ETFs in Settings → Narratives.
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
