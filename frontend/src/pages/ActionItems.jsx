import { useQuery } from '@tanstack/react-query'
import { api, fmt$, fmtPct, clsPl } from '../api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

const PRIO_ORDER = ['URGENT', 'ACTION', 'WATCH', 'INFO']

function PrioBadge({ prio }) {
  if (prio === 'URGENT') return <Badge variant="destructive">URGENT</Badge>
  if (prio === 'ACTION') return <Badge variant="outline" className="bg-warn/15 text-warn border-warn/30">ACTION</Badge>
  if (prio === 'WATCH') return <Badge variant="secondary">WATCH</Badge>
  return <Badge variant="outline">INFO</Badge>
}

function MarketStrip({ market }) {
  const vixCls = market.vix > 35 ? 'text-loss' : market.vix > 25 ? 'text-warn' : 'text-gain'
  return (
    <div className="flex gap-4 text-sm text-muted-foreground">
      <span>VIX <span className={cn('tnum font-semibold', vixCls)}>{market.vix?.toFixed(1) ?? '-'}</span></span>
      <span>SPY RSI <span className="tnum font-semibold text-foreground">{market.spy_rsi?.toFixed(1) ?? '-'}</span></span>
      <span>QQQ RSI <span className="tnum font-semibold text-foreground">{market.qqq_rsi?.toFixed(1) ?? '-'}</span></span>
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Skeleton className="h-5 w-64" />
      </div>
      {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-[88px] rounded-xl" />)}
      <p className="text-xs text-muted-foreground">Fetching live prices &amp; analysis… this may take 15-30 seconds</p>
    </div>
  )
}

export default function ActionItems() {
  const itemsQ = useQuery({ queryKey: ['action-items'], queryFn: api.actionItems })

  if (itemsQ.isLoading) return <LoadingSkeleton />
  if (itemsQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {itemsQ.error.message} - is the API server running? (trading server)
        </AlertDescription>
      </Alert>
    )
  }

  const data = itemsQ.data
  const items = data?.items || []
  const market = data?.market || {}
  const snaps = data?.snapshots || {}

  const byPrio = { URGENT: [], ACTION: [], WATCH: [], INFO: [] }
  for (const item of items) {
    const p = item.priority || 'INFO'
    ;(byPrio[p] || byPrio.INFO).push(item)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <MarketStrip market={market} />
        <Button
          variant="outline" size="sm" className="ml-auto"
          onClick={() => itemsQ.refetch()}
          disabled={itemsQ.isFetching}
        >
          {itemsQ.isFetching ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>

      {items.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No action items - market may be closed or no signals detected.
          </CardContent>
        </Card>
      )}

      {PRIO_ORDER.map(prio => {
        const group = byPrio[prio]
        if (!group.length) return null
        return (
          <div key={prio} className="space-y-2">
            <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {prio} ({group.length})
            </div>
            <div className="space-y-2">
              {group.map((item, i) => {
                const snap = item.ticker ? snaps[item.ticker] : null
                return (
                  <Card key={i}>
                    <CardContent className="flex items-start gap-3 px-4 py-3">
                      <span className="tnum mt-0.5 w-5 shrink-0 text-right text-xs text-muted-foreground">{i + 1}</span>
                      <div className="mt-0.5 shrink-0">
                        <PrioBadge prio={prio} />
                      </div>
                      <div className="min-w-0 space-y-1">
                        <div className="text-sm">
                          {item.ticker && <span className="mr-2 font-semibold">{item.ticker}</span>}
                          {item.action}
                        </div>
                        {item.detail && (
                          <div className="text-xs text-muted-foreground">{item.detail}</div>
                        )}
                        {snap && (
                          <div className="tnum text-xs text-muted-foreground">
                            Price {fmt$(snap.price)}
                            {snap.change_pct != null && (
                              <span className={clsPl(snap.change_pct)}> ({fmtPct(snap.change_pct)})</span>
                            )}
                            {snap.rsi != null && (
                              <span> · RSI <span className={cn(snap.rsi > 70 ? 'text-loss' : snap.rsi < 35 ? 'text-gain' : '')}>{snap.rsi.toFixed(1)}</span></span>
                            )}
                          </div>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
