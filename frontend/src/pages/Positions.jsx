import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, fmt$, fmtPct, clsPl } from '../api'
import { TypeBadge } from './Dashboard'
import { TickerChartDialog } from '@/components/ticker-chart'
import { TickerCombobox } from '@/components/ticker-combobox'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

const MODAL_TITLES = { buy: 'Buy / Add Position', sell: 'Sell Position', stop: 'Update Stop' }

function TradeDialog({ modal, accountNames = [], onClose }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    account: modal.acct || '',
    ticker: modal.ticker || '',
    shares: '',
    price: '',
    stop: '',
    ptype: 'L',
    thesis: '',
  })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)
  const mode = modal.mode
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setErr(null)
    try {
      if (mode === 'buy') {
        await api.buy({ ...form, shares: +form.shares, price: +form.price, stop: form.stop ? +form.stop : null })
      } else if (mode === 'sell') {
        await api.sell({ account: form.account, ticker: form.ticker, shares: +form.shares, price: +form.price })
      } else if (mode === 'stop') {
        await api.stop({ account: form.account, ticker: form.ticker, stop_price: +form.stop })
      }
      toast.success(`${MODAL_TITLES[mode]} - ${form.ticker} saved`)
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      onClose()
    } catch (e) {
      setErr(e.message)
      setLoading(false)
    }
  }

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{MODAL_TITLES[mode]}</DialogTitle>
          <DialogDescription>
            Updates positions.json through the token-authenticated API.
          </DialogDescription>
        </DialogHeader>
        {err && (
          <Alert variant="destructive">
            <AlertDescription>{err}</AlertDescription>
          </Alert>
        )}
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Account</Label>
              <Select value={form.account} onValueChange={v => set('account', v)} required>
                <SelectTrigger className="w-full"><SelectValue placeholder="Select" /></SelectTrigger>
                <SelectContent>
                  {accountNames.map(n => <SelectItem key={n} value={n}>{n}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Ticker</Label>
              {mode === 'buy' ? (
                <TickerCombobox
                  value={form.ticker}
                  className="w-full"
                  onSelect={sel => setForm(f => ({
                    ...f, ticker: sel.symbol,
                    price: f.price || (sel.price ?? ''),
                  }))}
                />
              ) : (
                <Input
                  value={form.ticker}
                  onChange={e => set('ticker', e.target.value.toUpperCase())}
                  placeholder="AAPL" required
                />
              )}
            </div>
          </div>

          {mode !== 'stop' && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Shares</Label>
                <Input type="number" min="0" step="any" value={form.shares} onChange={e => set('shares', e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label>Price</Label>
                <Input type="number" min="0" step="any" value={form.price} onChange={e => set('price', e.target.value)} required />
              </div>
            </div>
          )}

          {(mode === 'buy' || mode === 'stop') && (
            <div className="space-y-1.5">
              <Label>Stop Price</Label>
              <Input type="number" min="0" step="any" value={form.stop} onChange={e => set('stop', e.target.value)} placeholder="optional" />
            </div>
          )}

          {mode === 'buy' && (
            <>
              <div className="space-y-1.5">
                <Label>Type</Label>
                <Select value={form.ptype} onValueChange={v => set('ptype', v)}>
                  <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="L">L - Long swing</SelectItem>
                    <SelectItem value="S">S - Short-term</SelectItem>
                    <SelectItem value="Lifetime">Lifetime</SelectItem>
                    <SelectItem value="Spec">Spec</SelectItem>
                    <SelectItem value="I">I - Income</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Thesis</Label>
                <Input value={form.thesis} onChange={e => set('thesis', e.target.value)} placeholder="Why are you buying?" />
              </div>
            </>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant={mode === 'sell' ? 'destructive' : 'default'} disabled={loading}>
              {loading ? 'Saving…' : mode === 'buy' ? 'Buy' : mode === 'sell' ? 'Sell' : 'Update Stop'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const FUNDS_MODES = [
  { value: 'deposit', label: 'Deposit - add funds' },
  { value: 'withdraw', label: 'Withdraw funds' },
  { value: 'set', label: 'Set exact balance' },
]

function FundsDialog({ acctName, currentCash, onClose }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState('deposit')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    try {
      const res = await api.cash({ account: acctName, amount: +amount, mode })
      toast.success(res.message)
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      onClose()
    } catch (e) {
      toast.error(e.message)
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={open => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Manage Funds - {acctName}</DialogTitle>
          <DialogDescription className="tnum">
            Current cash: {fmt$(currentCash)}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label>Action</Label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {FUNDS_MODES.map(m => <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Amount ($)</Label>
            <Input type="number" min="0" step="any" className="tnum" value={amount}
              onChange={e => setAmount(e.target.value)} required autoFocus />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={busy || !amount}>
              {busy ? 'Saving…' : mode === 'deposit' ? 'Deposit' : mode === 'withdraw' ? 'Withdraw' : 'Set balance'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function PositionTable({ acctName, acct, prices, onModal, onTicker, onFunds }) {
  const positions = acct.positions || []
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {acctName} - Cash {fmt$(acct.cash)}
        </CardTitle>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => onFunds(acctName)}>Funds</Button>
          <Button size="sm" onClick={() => onModal({ mode: 'buy', acct: acctName })}>+ Buy</Button>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Ticker</TableHead>
              <TableHead className="text-right">Shares</TableHead>
              <TableHead className="text-right">Avg Cost</TableHead>
              <TableHead className="text-right">Price</TableHead>
              <TableHead className="text-right">Day</TableHead>
              <TableHead className="text-right">P&L $</TableHead>
              <TableHead className="text-right">P&L %</TableHead>
              <TableHead className="text-right">Stop</TableHead>
              <TableHead className="text-right">RSI</TableHead>
              <TableHead>Type</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {positions.map(p => {
              const snap = prices[p.ticker] || {}
              const price = snap.price ?? p.avg_cost
              const pl = (price - p.avg_cost) * p.shares
              const plPct = (price - p.avg_cost) / p.avg_cost * 100
              const stopPct = p.stop ? (p.stop - price) / price * 100 : null
              return (
                <TableRow key={p.ticker}>
                  <TableCell className="font-semibold">
                    <button type="button" className="font-semibold hover:underline" onClick={() => onTicker(p.ticker)}>
                      {p.ticker}
                    </button>
                  </TableCell>
                  <TableCell className="tnum text-right">{p.shares}</TableCell>
                  <TableCell className="tnum text-right">{fmt$(p.avg_cost)}</TableCell>
                  <TableCell className="tnum text-right">{fmt$(price)}</TableCell>
                  <TableCell className={cn('tnum text-right', clsPl(snap.change_pct))}>{fmtPct(snap.change_pct)}</TableCell>
                  <TableCell className={cn('tnum text-right', clsPl(pl))}>{fmt$(pl)}</TableCell>
                  <TableCell className={cn('tnum text-right', clsPl(plPct))}>{fmtPct(plPct)}</TableCell>
                  <TableCell className="tnum text-right">
                    {p.stop ? (
                      <span>
                        {fmt$(p.stop)}{' '}
                        <span className="text-muted-foreground">({fmtPct(stopPct)})</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell className={cn('tnum text-right', snap.rsi > 70 ? 'text-loss' : snap.rsi < 35 ? 'text-gain' : '')}>
                    {snap.rsi ? snap.rsi.toFixed(0) : <span className="text-muted-foreground">-</span>}
                  </TableCell>
                  <TableCell><TypeBadge type={p.type} /></TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => onModal({ mode: 'sell', acct: acctName, ticker: p.ticker })}>Sell</Button>
                      <Button variant="ghost" size="sm" onClick={() => onModal({ mode: 'stop', acct: acctName, ticker: p.ticker })}>Stop</Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {positions.length === 0 && (
              <TableRow>
                <TableCell colSpan={11} className="py-8 text-center text-muted-foreground">No positions</TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function PendingOrders({ accounts }) {
  const rows = Object.entries(accounts).flatMap(([acctName, acct]) =>
    (acct.positions || []).flatMap(p =>
      (p.pending_orders || []).map((o, i) => ({ key: `${acctName}-${p.ticker}-${i}`, acctName, ticker: p.ticker, ...o }))
    )
  )
  if (rows.length === 0) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Pending Orders
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Acct</TableHead>
              <TableHead>Ticker</TableHead>
              <TableHead>Order</TableHead>
              <TableHead className="text-right">Shares</TableHead>
              <TableHead className="text-right">Limit</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(o => (
              <TableRow key={o.key}>
                <TableCell className="text-muted-foreground">{o.acctName}</TableCell>
                <TableCell className="font-semibold">{o.ticker}</TableCell>
                <TableCell className="capitalize">{o.order} {o.type?.replace('_', ' ')}</TableCell>
                <TableCell className="tnum text-right">{o.shares}</TableCell>
                <TableCell className="tnum text-right">{fmt$(o.price)}</TableCell>
                <TableCell><Badge variant="outline" className="font-normal">{o.status}</Badge></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

export default function Positions() {
  const [modal, setModal] = useState(null)
  const [chartTicker, setChartTicker] = useState(null)
  const [fundsAcct, setFundsAcct] = useState(null)
  const positionsQ = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const pricesQ = useQuery({ queryKey: ['prices'], queryFn: api.prices, refetchInterval: 120_000 })

  if (positionsQ.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-[320px] rounded-xl" />
        <Skeleton className="h-[320px] rounded-xl" />
      </div>
    )
  }
  if (positionsQ.error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{positionsQ.error.message}</AlertDescription>
      </Alert>
    )
  }

  const prices = pricesQ.data ?? {}
  const accounts = positionsQ.data.accounts ?? {}
  const accountNames = Object.keys(accounts)

  if (accountNames.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No accounts yet - run the setup wizard to create your portfolio.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {Object.entries(accounts).map(([name, acct]) => (
        <PositionTable key={name} acctName={name} acct={acct} prices={prices}
          onModal={setModal} onTicker={setChartTicker} onFunds={setFundsAcct} />
      ))}
      <PendingOrders accounts={accounts} />
      {modal && <TradeDialog modal={modal} accountNames={accountNames} onClose={() => setModal(null)} />}
      {fundsAcct && (
        <FundsDialog acctName={fundsAcct} currentCash={accounts[fundsAcct]?.cash ?? 0}
          onClose={() => setFundsAcct(null)} />
      )}
      {chartTicker && (
        <TickerChartDialog ticker={chartTicker} open onClose={() => setChartTicker(null)} />
      )}
    </div>
  )
}
