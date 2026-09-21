import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Wallet, ListChecks, TrendingUp, ArrowLeftRight,
  Radar, Newspaper, Globe, Layers, Sparkles, MessageSquare,
  CandlestickChart, FlaskConical,
} from 'lucide-react'
import { Settings as SettingsIcon } from 'lucide-react'
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel,
  SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem,
} from '@/components/ui/sidebar'

const GROUPS = [
  {
    label: 'Portfolio',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/positions', label: 'Positions', icon: Wallet },
      { to: '/actions', label: 'Actions', icon: ListChecks },
      { to: '/performance', label: 'Performance', icon: TrendingUp },
      { to: '/trades', label: 'Trades', icon: ArrowLeftRight },
    ],
  },
  {
    label: 'AI Analyst',
    items: [
      { to: '/briefing', label: 'Briefing', icon: Sparkles },
      { to: '/chat', label: 'Chat', icon: MessageSquare },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { to: '/scan', label: 'Scan', icon: Radar },
      { to: '/news', label: 'News', icon: Newspaper },
      { to: '/themes', label: 'Macro Themes', icon: Globe },
      { to: '/etfs', label: 'ETFs', icon: Layers },
      { to: '/backtest', label: 'Backtest', icon: FlaskConical },
    ],
  },
]

// Page titles for the header breadcrumb, keyed by path
export const PAGE_TITLES = {
  ...Object.fromEntries(GROUPS.flatMap(g => g.items.map(i => [i.to, i.label]))),
  '/settings': 'Settings',
}

export function AppSidebar() {
  const { pathname } = useLocation()
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <div className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <CandlestickChart className="size-4" />
          </div>
          <span className="text-sm font-semibold tracking-tight">TraderAI</span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        {GROUPS.map(group => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map(item => {
                  const active = item.end ? pathname === item.to : pathname.startsWith(item.to)
                  return (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton asChild isActive={active}>
                        <NavLink to={item.to} end={item.end}>
                          <item.icon />
                          <span>{item.label}</span>
                        </NavLink>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild isActive={pathname.startsWith('/settings')}>
              <NavLink to="/settings">
                <SettingsIcon />
                <span>Settings</span>
              </NavLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
