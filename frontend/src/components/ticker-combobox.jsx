import { useEffect, useRef, useState } from 'react'
import { Check, ChevronsUpDown, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command'
import { cn } from '@/lib/utils'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Searchable ticker picker: type a company name or symbol, pick the exact
 * security (symbol · name · exchange), and get its live quote back.
 *
 * onSelect({ symbol, name, exchange, type, price }) - price may be null.
 */
export function TickerCombobox({ value, onSelect, className, placeholder = 'Search stock…' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const debounceRef = useRef(null)

  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const q = query.trim()
    if (q.length < 1) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await fetch(`${BASE}/api/search-tickers?q=${encodeURIComponent(q)}`)
        const data = await res.json()
        setResults(data.results ?? [])
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query, open])

  async function pick(r) {
    setOpen(false)
    setQuery('')
    let price = null
    try {
      const res = await fetch(`${BASE}/api/quote/${r.symbol}`)
      price = (await res.json()).price
    } catch { /* price stays null */ }
    onSelect({ ...r, price })
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button" variant="outline" role="combobox" aria-expanded={open}
          className={cn('justify-between font-normal', !value && 'text-muted-foreground', className)}
        >
          {value || placeholder}
          <ChevronsUpDown className="ml-1 size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[320px] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Type a symbol or company name…" value={query} onValueChange={setQuery} />
          <CommandList>
            {searching && (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
                <Loader2 className="size-3 animate-spin" /> Searching…
              </div>
            )}
            {!searching && query && results.length === 0 && (
              <CommandEmpty>No matches - check the spelling.</CommandEmpty>
            )}
            <CommandGroup>
              {results.map(r => (
                <CommandItem key={r.symbol} value={r.symbol} onSelect={() => pick(r)}>
                  <Check className={cn('size-3.5', value === r.symbol ? 'opacity-100' : 'opacity-0')} />
                  <span className="font-semibold">{r.symbol}</span>
                  <span className="truncate text-muted-foreground">{r.name}</span>
                  <span className="ml-auto text-[10px] uppercase text-muted-foreground">{r.exchange}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
