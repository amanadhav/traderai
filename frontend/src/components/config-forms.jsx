import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Trash2, Plus } from 'lucide-react'
import { TickerCombobox } from '@/components/ticker-combobox'
import { cn } from '@/lib/utils'

/* Shared form sections used by the Setup wizard and the Settings page.
   All are controlled: value + onChange(next). */

// ── Profile ──────────────────────────────────────────────────────────────────

export const TOLERANCES = [
  { value: 'conservative', label: 'Conservative', desc: 'Protect capital first. Small drawdowns, tight stops, income tilt.' },
  { value: 'balanced', label: 'Balanced', desc: 'Swing trades with discipline plus long-term compounders.' },
  { value: 'aggressive', label: 'Aggressive', desc: 'Comfortable with 20%+ drawdowns chasing growth.' },
  { value: 'speculative', label: 'Speculative', desc: 'Small caps and pre-profit bets with strict exit rules.' },
]

export function ProfileForm({ value, onChange }) {
  const set = (k, v) => onChange({ ...value, [k]: v })
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Your name</Label>
          <Input value={value.name || ''} onChange={e => set('name', e.target.value)} placeholder="Optional" />
        </div>
        <div className="space-y-1.5">
          <Label>Experience</Label>
          <Select value={value.experience} onValueChange={v => set('experience', v)}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="beginner">Beginner - first year of investing</SelectItem>
              <SelectItem value="intermediate">Intermediate - a few years in</SelectItem>
              <SelectItem value="advanced">Advanced - trades actively</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Time horizon (years)</Label>
          <Input
            type="number" min="1" max="50"
            value={value.horizon_years ?? 10}
            onChange={e => set('horizon_years', +e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label>Primary objective</Label>
          <Select value={value.objective} onValueChange={v => set('objective', v)}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="income">Income - dividends and stability</SelectItem>
              <SelectItem value="balanced">Balanced - growth with discipline</SelectItem>
              <SelectItem value="growth">Growth - maximize long-term value</SelectItem>
              <SelectItem value="speculation">Speculation - asymmetric bets</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="space-y-2">
        <Label>How do you react when a position drops 15%?</Label>
        <div className="grid gap-2 sm:grid-cols-2">
          {TOLERANCES.map(t => (
            <button
              key={t.value}
              type="button"
              onClick={() => set('risk_tolerance', t.value)}
              className={cn(
                'rounded-lg border p-3 text-left transition-colors hover:bg-accent',
                value.risk_tolerance === t.value && 'border-primary bg-accent',
              )}
            >
              <div className="text-sm font-medium">{t.label}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{t.desc}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Accounts ─────────────────────────────────────────────────────────────────

const POLICIES = [
  { value: 'active', label: 'Active - stops required, positions managed' },
  { value: 'lifetime', label: 'Lifetime - compounders, never sold on dips' },
  { value: 'income', label: 'Income - dividends, low turnover' },
  { value: 'spec', label: 'Spec - small bets, strict exits' },
]

export function AccountsForm({ value, onChange }) {
  const update = (i, patch) => onChange(value.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  const remove = (i) => onChange(value.filter((_, j) => j !== i))
  const add = () => onChange([...value, { name: `ACCOUNT${value.length + 1}`, policy: 'active', stops_required: true, sector_limits: {} }])
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Name your brokerage accounts and give each a policy. The AI analyst and action
        engine follow each account's policy - a "lifetime" account is never sold on volatility.
      </p>
      {value.map((a, i) => (
        <Card key={i}>
          <CardContent className="flex flex-wrap items-end gap-3 pt-4">
            <div className="space-y-1.5">
              <Label>Name</Label>
              <Input
                className="w-36"
                value={a.name}
                onChange={e => update(i, { name: e.target.value.toUpperCase().replace(/\s+/g, '_') })}
              />
            </div>
            <div className="min-w-56 flex-1 space-y-1.5">
              <Label>Policy</Label>
              <Select value={a.policy} onValueChange={v => update(i, { policy: v, stops_required: v === 'active' })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {POLICIES.map(p => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Switch checked={!!a.stops_required} onCheckedChange={v => update(i, { stops_required: v })} />
              <Label className="text-xs text-muted-foreground">Stops required</Label>
            </div>
            {value.length > 1 && (
              <Button variant="ghost" size="icon" className="mb-1" onClick={() => remove(i)}>
                <Trash2 className="size-4" />
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
      <Button variant="outline" size="sm" onClick={add}><Plus /> Add account</Button>
    </div>
  )
}

// ── Rules ────────────────────────────────────────────────────────────────────

const RULE_FIELDS = [
  { key: 'score_entry_threshold', label: 'Entry score threshold', suffix: '/180', min: 0, max: 180, desc: 'Minimum score before a buy is even considered' },
  { key: 'score_strong_threshold', label: 'Strong score', suffix: '/180', min: 0, max: 180 },
  { key: 'score_conviction_threshold', label: 'Conviction score', suffix: '/180', min: 0, max: 180 },
  { key: 'max_risk_per_trade_pct', label: 'Max risk per trade', suffix: '%', step: 0.25, desc: 'Percent of equity risked on one position (1-2% is standard)' },
  { key: 'max_portfolio_heat_pct', label: 'Max portfolio heat', suffix: '%', step: 0.5, desc: 'Total open risk across all positions' },
  { key: 'max_drawdown_pct', label: 'Max drawdown', suffix: '%', step: 1, desc: 'Hard stop from peak equity' },
  { key: 'max_position_pct', label: 'Max single position', suffix: '%', step: 1 },
  { key: 'max_positions', label: 'Max positions', suffix: '', step: 1 },
  { key: 'cash_floor_pct', label: 'Cash floor', suffix: '%', step: 1, desc: 'Never deploy below this cash level' },
  { key: 'default_stop_pct', label: 'Default stop distance', suffix: '%', step: 1 },
  { key: 'earnings_blackout_days', label: 'Earnings blackout', suffix: 'days', step: 1, desc: 'Never add within N days of earnings' },
  { key: 'min_add_signals', label: 'Signals required to add', suffix: '', min: 0, max: 5, step: 1 },
  { key: 'atr_stop_multiple', label: 'ATR stop multiple', suffix: 'x ATR', step: 0.25, desc: 'Stop distance when stop style is ATR' },
  { key: 'reward_risk_target', label: 'Reward:risk target', suffix: 'R', step: 0.25, desc: 'Take-profit at N x risk distance' },
  { key: 'swing_max_hold_days', label: 'Max swing hold', suffix: 'days', step: 1, desc: 'Flag Swing positions held longer than this' },
]

export function RulesForm({ value, onChange }) {
  const set = (k, v) => onChange({ ...value, [k]: v })
  return (
    <div className="space-y-4">
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
        {RULE_FIELDS.map(f => (
          <div key={f.key} className="space-y-1.5">
            <Label className="flex items-baseline justify-between">
              <span>{f.label}</span>
              {f.suffix && <span className="text-[10px] text-muted-foreground">{f.suffix}</span>}
            </Label>
            <Input
              type="number"
              min={f.min ?? 0} max={f.max} step={f.step ?? 1}
              value={value[f.key] ?? ''}
              onChange={e => set(f.key, e.target.value === '' ? 0 : +e.target.value)}
              className="tnum"
            />
            {f.desc && <p className="text-[11px] leading-snug text-muted-foreground">{f.desc}</p>}
          </div>
        ))}
        <div className="space-y-1.5">
          <Label>Stop style</Label>
          <Select value={value.stop_style} onValueChange={v => set('stop_style', v)}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="fixed_pct">Fixed % below entry</SelectItem>
              <SelectItem value="trailing">Trailing stop</SelectItem>
              <SelectItem value="atr">ATR-based (volatility-scaled)</SelectItem>
              <SelectItem value="none">No default stops</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Averaging down</Label>
          <Select value={value.averaging_down} onValueChange={v => set('averaging_down', v)}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="never">Never add to a loser</SelectItem>
              <SelectItem value="only_high_score">Only when score stays high</SelectItem>
              <SelectItem value="allowed">Allowed</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  )
}

// ── Portfolio (initial holdings + cash per account) ──────────────────────────

const POSITION_TYPES = [
  { value: 'L', label: 'Long' },
  { value: 'S', label: 'Swing' },
  { value: 'I', label: 'Income' },
  { value: 'Lifetime', label: 'Lifetime' },
  { value: 'Spec', label: 'Spec' },
]

const EMPTY_POSITION = { ticker: '', shares: '', avg_cost: '', ptype: 'L' }

/**
 * value shape: { [accountName]: { cash: number|'', positions: [{ticker, shares, avg_cost, ptype}] } }
 * `accounts` is the account list from the Accounts step - rows follow it.
 */
export function PortfolioForm({ accounts, value, onChange }) {
  const acctState = (name) => value[name] ?? { cash: '', positions: [] }
  const setAcct = (name, patch) => onChange({ ...value, [name]: { ...acctState(name), ...patch } })
  const setPos = (name, i, patch) => {
    const positions = acctState(name).positions.map((p, j) => (j === i ? { ...p, ...patch } : p))
    setAcct(name, { positions })
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Enter what you currently hold in each account - cash on hand plus any existing
        positions (ticker, share count, and your average cost per share). Starting from
        zero? Just set your cash and skip positions; you can buy from the Positions page later.
      </p>
      {accounts.map(a => {
        const s = acctState(a.name)
        return (
          <Card key={a.name}>
            <CardContent className="space-y-3 pt-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div className="text-sm font-semibold">{a.name}</div>
                <div className="space-y-1.5">
                  <Label>Cash on hand ($)</Label>
                  <Input
                    type="number" min="0" step="any" className="tnum w-40"
                    value={s.cash}
                    onChange={e => setAcct(a.name, { cash: e.target.value })}
                    placeholder="0.00"
                  />
                </div>
              </div>
              {s.positions.map((p, i) => (
                <div key={i} className="rounded-lg border p-2">
                  <div className="flex flex-wrap items-end gap-2">
                    <div className="space-y-1">
                      <Label className="text-[11px]">Stock</Label>
                      <TickerCombobox
                        value={p.ticker}
                        className="w-40"
                        onSelect={sel => setPos(a.name, i, {
                          ticker: sel.symbol,
                          name: sel.name,
                          live_price: sel.price,
                          // prefill with the live price ONLY when empty - edit to YOUR avg cost
                          avg_cost: p.avg_cost || (sel.price ?? ''),
                        })}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Shares</Label>
                      <Input type="number" min="0" step="any" className="tnum w-24" value={p.shares}
                        onChange={e => setPos(a.name, i, { shares: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Avg cost / share ($)</Label>
                      <Input type="number" min="0" step="any" className="tnum w-32" value={p.avg_cost}
                        onChange={e => setPos(a.name, i, { avg_cost: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px]">Type</Label>
                      <Select value={p.ptype} onValueChange={v => setPos(a.name, i, { ptype: v })}>
                        <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {POSITION_TYPES.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <Button variant="ghost" size="icon" className="mb-0.5"
                      onClick={() => setAcct(a.name, { positions: s.positions.filter((_, j) => j !== i) })}>
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                  {p.name && (
                    <p className="mt-1.5 text-[11px] text-muted-foreground">
                      {p.name}
                      {p.live_price != null && (
                        <> - trading at <span className="tnum">${p.live_price}</span> now.
                        {String(p.avg_cost) === String(p.live_price) && ' Avg cost prefilled with the live price - change it to what YOU paid.'}</>
                      )}
                    </p>
                  )}
                </div>
              ))}
              <Button variant="outline" size="sm"
                onClick={() => setAcct(a.name, { positions: [...s.positions, { ...EMPTY_POSITION }] })}>
                <Plus /> Add position
              </Button>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

// ── Narratives ───────────────────────────────────────────────────────────────

export function NarrativesForm({ value, onChange, available }) {
  const toggle = (key) =>
    onChange(value.includes(key) ? value.filter(k => k !== key) : [...value, key])
  const keys = Object.keys(available || {})
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Macro narratives you want tracked. Positions aligned with an active narrative get a
        scoring bonus and macro-status coverage in briefings. Selecting none tracks all of them.
      </p>
      <div className="flex flex-wrap gap-2">
        {keys.map(k => {
          const active = value.includes(k)
          return (
            <button key={k} type="button" onClick={() => toggle(k)}>
              <Badge
                variant={active ? 'default' : 'outline'}
                className="cursor-pointer px-3 py-1.5 font-normal"
              >
                {k.replace(/_/g, ' ')}
              </Badge>
            </button>
          )
        })}
      </div>
      {keys.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {value.length === 0 ? 'Tracking all narratives' : `Tracking ${value.length} of ${keys.length}`}
        </p>
      )}
    </div>
  )
}

// ── ETF watchlist ─────────────────────────────────────────────────────────────

export function EtfWatchlistForm({ value, onChange }) {
  return (
    <div className="space-y-1.5 pt-2">
      <Label>ETF watchlist</Label>
      <Input
        value={(value || []).join(', ')}
        onChange={e => onChange(
          e.target.value.toUpperCase().split(',').map(t => t.trim()).filter(Boolean)
        )}
        placeholder="SPY, QQQ, GLD"
      />
      <p className="text-[11px] text-muted-foreground">
        Comma-separated - shown with live technicals on the ETFs page.
      </p>
    </div>
  )
}

// ── AI behavior + appearance ─────────────────────────────────────────────────

export function AiAppearanceForm({ ai, appearance, paperMode, onChange }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Briefing tone</Label>
          <Select value={ai.briefing_tone} onValueChange={v => onChange({ ai: { ...ai, briefing_tone: v } })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="terse">Terse - headlines and decisions only</SelectItem>
              <SelectItem value="detailed">Detailed - full reasoning</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Recommendation style</Label>
          <Select value={ai.recommendation_style} onValueChange={v => onChange({ ai: { ...ai, recommendation_style: v } })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="explicit">Explicit - tell me exactly what to do</SelectItem>
              <SelectItem value="suggestive">Suggestive - options and trade-offs, I decide</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>AI model tier</Label>
          <Select value={ai.model_tier ?? 'budget'} onValueChange={v => onChange({ ai: { ...ai, model_tier: v } })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="budget">Budget - Haiku everywhere, pennies/day</SelectItem>
              <SelectItem value="quality">Quality - Sonnet for briefing & chat</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Daily AI budget</Label>
          <Input
            type="number" step="0.25" min="0.25"
            className="tnum"
            value={ai.daily_budget_usd ?? 1}
            onChange={e => onChange({ ai: { ...ai, daily_budget_usd: +e.target.value } })}
          />
          <p className="text-[11px] text-muted-foreground">
            Hard cap - AI calls stop when today's spend reaches this
          </p>
        </div>
        <div className="space-y-1.5">
          <Label>Theme</Label>
          <Select value={appearance.theme} onValueChange={v => onChange({ appearance: { ...appearance, theme: v } })}>
            <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="dark">Dark</SelectItem>
              <SelectItem value="light">Light</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-3 pt-6">
          <Switch checked={!!paperMode} onCheckedChange={v => onChange({ paper_mode: v })} />
          <div>
            <Label>Paper mode</Label>
            <p className="text-[11px] text-muted-foreground">Mark this portfolio as simulated</p>
          </div>
        </div>
      </div>
    </div>
  )
}
