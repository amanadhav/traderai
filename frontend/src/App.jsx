import { useEffect } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { configApi } from '@/lib/config-api'
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { AppSidebar, PAGE_TITLES } from '@/components/app-sidebar'
import { cn } from '@/lib/utils'
import Dashboard from './pages/Dashboard'
import Positions from './pages/Positions'
import ActionItems from './pages/ActionItems'
import Performance from './pages/Performance'
import Trades from './pages/Trades'
import ETFs from './pages/ETFs'
import Themes from './pages/Themes'
import News from './pages/News'
import Scan from './pages/Scan'
import Briefing from './pages/Briefing'
import Backtest from './pages/Backtest'
import Chat from './pages/Chat'
import Setup from './pages/Setup'
import Settings from './pages/Settings'

function MarketStat({ label, value, tone }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={cn('tnum text-xs font-semibold', tone)}>{value}</span>
    </span>
  )
}

function MarketBar() {
  const { data: m } = useQuery({
    queryKey: ['market'],
    queryFn: api.market,
    refetchInterval: 120_000,
  })
  if (!m) return null
  const rsiTone = (rsi) => (rsi > 75 ? 'text-loss' : rsi < 35 ? 'text-gain' : '')
  return (
    <div className="hidden items-center gap-4 rounded-full border bg-card px-4 py-1.5 md:flex">
      <MarketStat
        label="VIX"
        value={m.vix?.toFixed(1) ?? '-'}
        tone={m.vix > 35 ? 'text-loss' : m.vix > 25 ? 'text-warn' : 'text-gain'}
      />
      <Separator orientation="vertical" className="!h-3" />
      <MarketStat label="SPY" value={m.spy_price ? `$${m.spy_price.toFixed(2)}` : '-'} />
      <MarketStat label="RSI" value={m.spy_rsi?.toFixed(1) ?? '-'} tone={rsiTone(m.spy_rsi)} />
      <Separator orientation="vertical" className="!h-3" />
      <MarketStat label="QQQ" value={m.qqq_price ? `$${m.qqq_price.toFixed(2)}` : '-'} />
      <MarketStat label="RSI" value={m.qqq_rsi?.toFixed(1) ?? '-'} tone={rsiTone(m.qqq_rsi)} />
    </div>
  )
}

export default function App() {
  const { pathname } = useLocation()
  const configQ = useQuery({ queryKey: ['config'], queryFn: configApi.get })
  const config = configQ.data

  // Theme follows user config (dark is the default while loading)
  useEffect(() => {
    const theme = config?.appearance?.theme ?? 'dark'
    document.documentElement.classList.toggle('dark', theme !== 'light')
  }, [config?.appearance?.theme])

  // First run → onboarding wizard (standalone, no app chrome)
  if (pathname === '/setup') {
    return (
      <main className="min-h-screen bg-background p-4 md:p-6">
        <Setup />
      </main>
    )
  }
  if (config && !config.onboarded) {
    return <Navigate to="/setup" replace />
  }

  const title = PAGE_TITLES[pathname] ?? 'TraderAI'
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 !h-4" />
          <h1 className="text-sm font-medium">{title}</h1>
          {config?.paper_mode && (
            <Badge variant="outline" className="text-warn border-warn/40 font-normal">PAPER</Badge>
          )}
          <div className="ml-auto flex items-center gap-2">
            <MarketBar />
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/actions" element={<ActionItems />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/etfs" element={<ETFs />} />
            <Route path="/news" element={<News />} />
            <Route path="/themes" element={<Themes />} />
            <Route path="/scan" element={<Scan />} />
            <Route path="/briefing" element={<Briefing />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
