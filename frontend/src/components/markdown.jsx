import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

/** Markdown styled for the monochrome theme (briefing + chat replies). */
export function Markdown({ children, className }) {
  return (
    <div className={cn(
      'space-y-3 text-sm leading-relaxed',
      '[&_h1]:text-lg [&_h1]:font-semibold [&_h1]:mt-4',
      '[&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-4',
      '[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:uppercase [&_h3]:tracking-wider [&_h3]:text-muted-foreground [&_h3]:mt-4',
      '[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1',
      '[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:space-y-1',
      '[&_strong]:font-semibold',
      '[&_a]:underline [&_a]:underline-offset-2',
      '[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs',
      '[&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground',
      '[&_table]:w-full [&_table]:text-xs',
      '[&_th]:border-b [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-medium [&_th]:text-muted-foreground',
      '[&_td]:border-b [&_td]:border-border/50 [&_td]:px-2 [&_td]:py-1.5',
      '[&_hr]:border-border',
      className,
    )}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
