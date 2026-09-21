import { useQuery } from '@tanstack/react-query'
import { ExternalLink, Radio } from 'lucide-react'
import { api } from '../api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

function timeAgo(ts) {
  if (!ts) return ''
  const secs = Math.floor(Date.now() / 1000 - ts)
  if (secs < 3600) return `${Math.max(1, Math.floor(secs / 60))}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

function NarrativePulse({ p }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border/50 py-2.5 last:border-0">
      {p.active ? (
        <Badge variant="outline" className="border-gain/30 text-gain font-normal">
          <Radio className="size-3" /> ACTIVE
        </Badge>
      ) : (
        <Badge variant="outline" className="font-normal text-muted-foreground">quiet</Badge>
      )}
      <span className="text-sm font-medium capitalize">{p.narrative.replace(/_/g, ' ')}</span>
      {p.jev_probability != null && (
        <span className="tnum text-xs text-muted-foreground">
          Jev {Math.round(p.jev_probability * 100)}%
        </span>
      )}
      {p.keyword_hits.length > 0 && (
        <span className="text-xs text-muted-foreground">
          in the news: {p.keyword_hits.join(', ')}
        </span>
      )}
    </div>
  )
}

export default function Themes() {
  const newsQ = useQuery({
    queryKey: ['macro-news'],
    queryFn: api.macroNews,
    staleTime: 15 * 60_000,
    refetchInterval: 15 * 60_000,
  })

  if (newsQ.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-[200px] rounded-xl" />
        <Skeleton className="h-[400px] rounded-xl" />
      </div>
    )
  }
  if (newsQ.error) {
    return <Alert variant="destructive"><AlertDescription>{newsQ.error.message}</AlertDescription></Alert>
  }

  const { headlines = [], narratives = [] } = newsQ.data ?? {}

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Your Macro Themes - live pulse
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Themes you track (Settings → Narratives), checked against today's market
            headlines. Active themes boost scoring for aligned positions.
          </p>
        </CardHeader>
        <CardContent>
          {narratives.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">No themes tracked.</p>
          ) : (
            narratives.map(p => <NarrativePulse key={p.narrative} p={p} />)
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Market Headlines
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {headlines.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No headlines available - add a free FINNHUB_KEY to .env for the full feed.
            </p>
          )}
          {headlines.map((h, i) => (
            <a
              key={i}
              href={h.url || undefined}
              target="_blank" rel="noopener noreferrer"
              className={cn(
                'group block rounded-lg border p-3 transition-colors',
                h.url ? 'hover:bg-accent' : 'cursor-default',
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <span className="text-sm font-medium leading-snug group-hover:underline">
                  {h.title}
                </span>
                {h.url && <ExternalLink className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />}
              </div>
              <div className="mt-1 flex gap-2 text-xs text-muted-foreground">
                {h.source && <span>{h.source}</span>}
                {h.datetime && <span>{timeAgo(h.datetime)}</span>}
              </div>
              {h.summary && (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{h.summary}</p>
              )}
            </a>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
