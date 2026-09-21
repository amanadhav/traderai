import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CandlestickChart, ChevronLeft, ChevronRight, Check } from 'lucide-react'
import { configApi } from '@/lib/config-api'
import { ProfileForm, AccountsForm, PortfolioForm, RulesForm, NarrativesForm, EtfWatchlistForm, AiAppearanceForm } from '@/components/config-forms'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const STEPS = ['Profile', 'Accounts', 'Portfolio', 'Rules', 'Narratives', 'Behavior']

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function PresetPicker({ presets, selected, onSelect }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {Object.entries(presets).map(([key, p]) => (
        <button
          key={key}
          type="button"
          onClick={() => onSelect(key)}
          className={cn(
            'rounded-lg border p-3 text-left transition-colors hover:bg-accent',
            selected === key && 'border-primary bg-accent',
          )}
        >
          <div className="text-sm font-medium">{p.label}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{p.description}</div>
        </button>
      ))}
    </div>
  )
}

export default function Setup() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const presetsQ = useQuery({ queryKey: ['config-presets'], queryFn: configApi.presets })
  const configQ = useQuery({ queryKey: ['config'], queryFn: configApi.get })

  const [step, setStep] = useState(0)
  const [saving, setSaving] = useState(false)
  const [draft, setDraft] = useState(null)
  // { [accountName]: { cash, positions: [{ticker, shares, avg_cost, ptype}] } }
  const [portfolio, setPortfolio] = useState({})

  if (presetsQ.isLoading || configQ.isLoading) {
    return <div className="mx-auto max-w-2xl"><Skeleton className="h-[480px] rounded-xl" /></div>
  }
  if (presetsQ.error || configQ.error) {
    return (
      <div className="mx-auto max-w-2xl text-sm text-loss">
        Could not reach the API - is the backend running on port 8000?
      </div>
    )
  }

  const presets = presetsQ.data.presets
  const toleranceToPreset = presetsQ.data.tolerance_to_preset
  const narratives = presetsQ.data.available_narratives

  const d = draft ?? configQ.data
  const setD = (patch) => setDraft({ ...d, ...patch })

  // picking a risk tolerance also proposes the matching preset + its rules
  const onProfileChange = (profile) => {
    const patch = { profile }
    if (profile.risk_tolerance !== d.profile.risk_tolerance) {
      const presetKey = toleranceToPreset[profile.risk_tolerance]
      if (presetKey && presets[presetKey]) {
        patch.preset = presetKey
        patch.rules = { ...presets[presetKey].rules }
      }
    }
    setDraft({ ...d, ...patch })
  }

  const onPresetSelect = (key) => {
    setDraft({ ...d, preset: key, rules: { ...presets[key].rules } })
  }

  async function finish() {
    setSaving(true)
    try {
      // 1. Create the portfolio FIRST - the setup endpoint is open only
      //    while onboarded is still false.
      const setupAccounts = d.accounts.map(a => {
        const s = portfolio[a.name] ?? { cash: '', positions: [] }
        return {
          name: a.name,
          cash: +s.cash || 0,
          positions: (s.positions || [])
            .filter(p => p.ticker && +p.shares > 0 && +p.avg_cost > 0)
            .map(p => ({ ticker: p.ticker, shares: +p.shares, avg_cost: +p.avg_cost, ptype: p.ptype })),
        }
      })
      const res = await fetch(`${API_BASE}/api/setup/portfolio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accounts: setupAccounts }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'portfolio setup failed')
      }

      // 2. Then save the config and mark onboarded.
      const saved = await configApi.save({
        profile: d.profile,
        preset: d.preset,
        rules: d.rules,
        accounts: d.accounts,
        narratives: d.narratives,
        etf_watchlist: d.etf_watchlist,
        ai: d.ai,
        appearance: d.appearance,
        paper_mode: d.paper_mode,
        onboarded: true,
      })
      // seed the cache so the onboarding gate sees onboarded=true immediately
      queryClient.setQueryData(['config'], saved)
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      const firstName = d.profile?.name?.trim().split(/\s+/)[0]
      toast.success(firstName ? `Welcome, ${firstName} - your system is ready` : 'Your system is configured - portfolio created')
      navigate('/')
    } catch (e) {
      toast.error(e.message)
      setSaving(false)
    }
  }

  const stepBody = [
    <ProfileForm key="p" value={d.profile} onChange={onProfileChange} />,
    <AccountsForm key="a" value={d.accounts} onChange={accounts => setD({ accounts })} />,
    <PortfolioForm key="pf" accounts={d.accounts} value={portfolio} onChange={setPortfolio} />,
    <div key="r" className="space-y-5">
      <div className="space-y-2">
        <div className="text-sm font-medium">Start from a preset</div>
        <PresetPicker presets={presets} selected={d.preset} onSelect={onPresetSelect} />
      </div>
      <div className="space-y-2">
        <div className="text-sm font-medium">Fine-tune every rule</div>
        <RulesForm value={d.rules} onChange={rules => setD({ rules })} />
      </div>
    </div>,
    <div key="n" className="space-y-4">
      <NarrativesForm value={d.narratives} onChange={narratives => setD({ narratives })} available={narratives} />
      <EtfWatchlistForm value={d.etf_watchlist} onChange={etf_watchlist => setD({ etf_watchlist })} />
    </div>,
    <AiAppearanceForm key="ai" ai={d.ai} appearance={d.appearance} paperMode={d.paper_mode} onChange={setD} />,
  ][step]

  const stepDescriptions = [
    'Who is this system for? Your answers pick sensible starting rules.',
    'Define your brokerage accounts and how each should be managed.',
    'What do you hold today? Cash and existing positions per account - the system tracks P&L from your average cost.',
    'These rules drive the scoring engine, action items, and every AI recommendation.',
    'Pick the macro themes you want tracked against your positions.',
    'How the AI analyst should talk to you, and how the app should look.',
  ]

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center gap-3 pt-4">
        <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <CandlestickChart className="size-5" />
        </div>
        <div>
          <h1 className="text-lg font-semibold leading-tight">Set up your TraderAI</h1>
          <p className="text-xs text-muted-foreground">
            Everything here can be changed later in Settings.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1">
        {STEPS.map((s, i) => (
          <button
            key={s}
            type="button"
            onClick={() => i < step && setStep(i)}
            className={cn(
              'flex-1 rounded-full px-2 py-1 text-center text-[11px] transition-colors',
              i === step ? 'bg-primary text-primary-foreground font-medium'
                : i < step ? 'bg-accent text-foreground cursor-pointer'
                : 'bg-muted text-muted-foreground',
            )}
          >
            {s}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{STEPS[step]}</CardTitle>
          <CardDescription>{stepDescriptions[step]}</CardDescription>
        </CardHeader>
        <CardContent>{stepBody}</CardContent>
      </Card>

      <div className="flex justify-between pb-8">
        <Button variant="ghost" onClick={() => setStep(s => s - 1)} disabled={step === 0}>
          <ChevronLeft /> Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button onClick={() => setStep(s => s + 1)}>
            Next <ChevronRight />
          </Button>
        ) : (
          <Button onClick={finish} disabled={saving}>
            <Check /> {saving ? 'Saving…' : 'Finish setup'}
          </Button>
        )}
      </div>
    </div>
  )
}
