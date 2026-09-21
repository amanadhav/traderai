import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

function timeAgo(ts) {
  if (!ts) return ''
  // accepts epoch seconds or an ISO date string
  const epoch = typeof ts === 'number' ? ts : Math.floor(new Date(ts).getTime() / 1000)
  if (!epoch || Number.isNaN(epoch)) return ''
  const diff = Math.floor((Date.now() / 1000) - epoch)
  if (diff < 0) return ''
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function LoadingSkeleton() {
  return (
    <div className="flex gap-4">
      <div className="w-32 space-y-2">
        {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-8 rounded-md" />)}
      </div>
      <div className="flex-1 space-y-2">
        {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-[64px] rounded-xl" />)}
      </div>
    </div>
  )
}

export default function News() {
  const [picked, setPicked] = useState(null)
  const newsQ = useQuery({ queryKey: ['news-all'], queryFn: api.newsAll })

  if (newsQ.isLoading) return <LoadingSkeleton />
  if (newsQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>Could not load news: {newsQ.error.message}</AlertDescription>
      </Alert>
    )
  }

  const news = newsQ.data ?? {}
  const tickers = Object.keys(news)
  const selected = picked && tickers.includes(picked) ? picked : tickers[0] ?? null
  const articles = selected ? (news[selected] || []) : []

  if (tickers.length === 0) {
    return (
      <div className="space-y-4">
        <Card>
          <CardContent className="py-10 text-center text-muted-foreground">
            No positions found.
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-4">
        <div className="flex w-32 shrink-0 flex-col gap-1">
          {tickers.map(t => (
            <Button
              key={t}
              variant={selected === t ? 'secondary' : 'ghost'}
              size="sm"
              className="justify-start"
              onClick={() => setPicked(t)}
            >
              <span className="font-semibold">{t}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">{news[t]?.length || 0}</span>
            </Button>
          ))}
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {selected} - Latest News
          </div>
          {articles.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center text-sm text-muted-foreground">
                No recent news.
              </CardContent>
            </Card>
          ) : (
            articles.map((article, i) => (
              <Card key={i}>
                <CardContent className="space-y-1 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <a
                      href={article.url || article.link || undefined}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={cn(
                        'min-w-0 flex-1 text-sm font-semibold leading-snug',
                        (article.url || article.link) && 'hover:underline underline-offset-2 cursor-pointer'
                      )}
                    >
                      {article.title}
                    </a>
                    <span className="whitespace-nowrap text-xs text-muted-foreground">
                      {timeAgo(article.providerPublishTime || article.published)}
                    </span>
                  </div>
                  {(article.source || article.publisher) && (
                    <div className="text-xs text-muted-foreground">{article.source || article.publisher}</div>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
