import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/**
 * Reference-style stat card: small uppercase label, big tabular number,
 * optional sub line and right-aligned slot (badge, sparkline, ...).
 */
export function StatCard({ label, value, sub, subClass, right, className }) {
  return (
    <Card className={cn('py-4', className)}>
      <CardContent className="flex items-start justify-between gap-2 px-4">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</div>
          <div className="tnum mt-1 truncate text-2xl font-semibold">{value}</div>
          {sub != null && <div className={cn('tnum mt-0.5 text-xs text-muted-foreground', subClass)}>{sub}</div>}
        </div>
        {right}
      </CardContent>
    </Card>
  )
}
