import type { ReactNode } from 'react'
import { CircleAlert, LoaderCircle, MapPin, MoveRight } from 'lucide-react'
import { Link } from 'react-router-dom'

export function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="heading-action">{action}</div>}</div>
}

export function LoadingState({ label = 'Ma’lumot yuklanmoqda' }: { label?: string }) {
  return <div className="state-row"><LoaderCircle className="spin" size={19} />{label}</div>
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="state-error"><CircleAlert size={18} /><span>{message}</span>{onRetry && <button className="text-button" onClick={onRetry}>Qayta urinish</button>}</div>
}

export function EmptyState({ title, description, icon: Icon = MapPin, action }: { title: string; description: string; icon?: typeof MapPin; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon size={22} /></span><strong>{title}</strong><p>{description}</p>{action}</div>
}

export function RouteLine({ from, to }: { from?: string; to?: string }) {
  return <div className="route-line-item"><span className="route-dot route-dot-from" /><div><strong>{from || 'Manzil aniqlanmagan'}</strong><MoveRight size={17} /><strong>{to || 'Manzil aniqlanmagan'}</strong></div><span className="route-dot route-dot-to" /></div>
}

export function ContentState({ loading, error, empty, onRetry, children }: { loading: boolean; error?: string; empty?: boolean; onRetry?: () => void; children: ReactNode }) {
  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} onRetry={onRetry} />
  if (empty) return <EmptyState title="Hozircha ma’lumot yo‘q" description="Yangi ma’lumot paydo bo‘lganda shu yerda ko‘rinadi." />
  return <>{children}</>
}

export function StatusBadge({ value }: { value?: string }) {
  const normalized = (value || 'unknown').toLowerCase()
  const tone = ['active', 'accepted', 'completed', 'paid', 'success', 'verified'].includes(normalized) ? 'positive' : ['pending', 'draft', 'driver_arrived', 'in_progress'].includes(normalized) ? 'pending' : 'muted'
  return <span className={`status-badge status-${tone}`}><i />{(value || 'Noma’lum').replaceAll('_', ' ')}</span>
}

export function FormNotice({ message }: { message: string }) {
  return message ? <p className="form-notice" role="status">{message}</p> : null
}

export function LinkAction({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="button button-outline" to={to}>{children}</Link>
}