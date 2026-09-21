import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { RotateCcw, Save } from 'lucide-react'
import { api } from '../api'
import { configApi } from '@/lib/config-api'
import { ProfileForm, AccountsForm, RulesForm, NarrativesForm, EtfWatchlistForm, AiAppearanceForm } from '@/components/config-forms'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'

function ResetPortfolioDialog({ open, onClose }) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const queryClient = useQueryClient()
  async function reset() {
    setBusy(true)
    try {
      const res = await fetch((import.meta.env.VITE_API_URL || 'http://localhost:8000') + '/api/reset-portfolio', {
        method: 'POST',
        headers: { 'X-API-Token': token },
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
      queryClient.invalidateQueries()
      toast.success('Portfolio reset to the example template')
      onClose()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reset portfolio</DialogTitle>
          <DialogDescription>
            Replaces positions.json with the example template. This erases your current
            positions (trade history is kept). Requires your API token from .env.
          </DialogDescription>
        </DialogHeader>
        <Input
          type="password" placeholder="TRADING_API_TOKEN"
          value={token} onChange={e => setToken(e.target.value)}
        />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" onClick={reset} disabled={busy || !token}>
            {busy ? 'Resetting…' : 'Reset portfolio'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function Settings() {
  const queryClient = useQueryClient()
  const configQ = useQuery({ queryKey: ['config'], queryFn: configApi.get })
  const presetsQ = useQuery({ queryKey: ['config-presets'], queryFn: configApi.presets })
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)

  if (configQ.isLoading || presetsQ.isLoading) return <Skeleton className="h-[480px] rounded-xl" />
  if (configQ.error) {
    return <Alert variant="destructive"><AlertDescription>{configQ.error.message}</AlertDescription></Alert>
  }

  const d = draft ?? configQ.data
  const setD = (patch) => setDraft({ ...d, ...patch })
  const dirty = draft !== null

  async function save() {
    setSaving(true)
    try {
      await configApi.save({
        profile: d.profile, preset: d.preset, rules: d.rules, accounts: d.accounts,
        narratives: d.narratives, etf_watchlist: d.etf_watchlist,
        ai: d.ai, appearance: d.appearance,
        paper_mode: d.paper_mode, onboarded: true,
      })
      queryClient.invalidateQueries({ queryKey: ['config'] })
      setDraft(null)
      toast.success('Settings saved - the engine and AI now follow your rules')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-base">Settings</CardTitle>
            <CardDescription>
              Your rules drive the scoring engine, action items, and every AI recommendation.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setResetOpen(true)}>
              <RotateCcw /> Reset portfolio
            </Button>
            <Button size="sm" onClick={save} disabled={!dirty || saving}>
              <Save /> {saving ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="rules">
            <TabsList className="mb-4">
              <TabsTrigger value="profile">Profile</TabsTrigger>
              <TabsTrigger value="accounts">Accounts</TabsTrigger>
              <TabsTrigger value="rules">Rules</TabsTrigger>
              <TabsTrigger value="narratives">Narratives</TabsTrigger>
              <TabsTrigger value="behavior">AI & Look</TabsTrigger>
            </TabsList>
            <TabsContent value="profile">
              <ProfileForm value={d.profile} onChange={profile => setD({ profile })} />
            </TabsContent>
            <TabsContent value="accounts">
              <AccountsForm value={d.accounts} onChange={accounts => setD({ accounts })} />
            </TabsContent>
            <TabsContent value="rules">
              <RulesForm value={d.rules} onChange={rules => setD({ rules })} />
            </TabsContent>
            <TabsContent value="narratives">
              <NarrativesForm
                value={d.narratives}
                onChange={narratives => setD({ narratives })}
                available={presetsQ.data?.available_narratives || {}}
              />
              <EtfWatchlistForm value={d.etf_watchlist} onChange={etf_watchlist => setD({ etf_watchlist })} />
            </TabsContent>
            <TabsContent value="behavior">
              <AiAppearanceForm ai={d.ai} appearance={d.appearance} paperMode={d.paper_mode} onChange={setD} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
      <ResetPortfolioDialog open={resetOpen} onClose={() => setResetOpen(false)} />
    </div>
  )
}
