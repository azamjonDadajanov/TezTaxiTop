import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, BadgeCheck, CircleAlert, CreditCard, ShieldCheck, WalletCards } from 'lucide-react'
import { api, dateTime, money, readableError, toArray, type ApiItem, type Order } from '../api'
import { useAuth } from '../authContext'
import { ContentState, FormNotice, PageHeading, RouteLine, StatusBadge } from '../components/ui'
import { useRoleMode } from './useRoleMode'

export function OrdersPage() {
  const queryClient = useQueryClient()
  const mode = useRoleMode()
  const driver = mode === 'driver'
  const orders = useQuery({ queryKey: ['my-orders', mode], queryFn: async () => toArray((await api.get<Order[] | { results: Order[] }>(`/orders/orders/my_orders/?role=${mode}`)).data) })
  const [error, setError] = useState('')
  const transition = useMutation({ mutationFn: async ({ id, action }: { id: number; action: string }) => api.post(`/orders/orders/${id}/${action}/`, ['reject', 'cancel', 'no_show'].includes(action) ? { reason: '' } : undefined), onSuccess: () => { setError(''); void queryClient.invalidateQueries({ queryKey: ['my-orders'] }) }, onError: (cause) => setError(readableError(cause)) })
  return <>
    <PageHeading eyebrow={driver ? 'HAYDOVCHI' : 'YO‘LOVCHI'} title="Buyurtmalar" description={driver ? 'Kelgan buyurtmalarni ko‘rib chiqing va holatini yangilang.' : 'Safar bo‘yicha yuborgan buyurtmalaringizni kuzating.'} />
    {error && <p className="inline-error"><CircleAlert size={15} />{error}</p>}
    <ContentState loading={orders.isLoading} error={orders.error ? readableError(orders.error) : undefined} empty={orders.data?.length === 0} onRetry={() => void orders.refetch()}><div className="record-list">{orders.data?.map((order) => <article className="record-card" key={order.id}><div className="record-top"><span className="record-id">BUYURTMA #{order.id}</span><StatusBadge value={order.status_display || order.status} /></div><RouteLine from={order.trip_route?.split(' → ')[0]} to={order.trip_route?.split(' → ')[1]} /><div className="record-detail-grid"><span>{dateTime(order.departure_time)}</span><span>{driver ? order.passenger_name : order.driver_name}</span><strong>{money(order.total_amount)}</strong></div><div className="record-actions">{driver && order.status === 'pending' && <><button className="button button-dark button-small" onClick={() => transition.mutate({ id: order.id, action: 'accept' })}>Qabul qilish</button><button className="button button-outline button-small" onClick={() => transition.mutate({ id: order.id, action: 'reject' })}>Rad etish</button></>}{driver && order.status === 'accepted' && <button className="button button-dark button-small" onClick={() => transition.mutate({ id: order.id, action: 'arrived' })}>Yetib keldim</button>}{driver && order.status === 'driver_arrived' && <button className="button button-dark button-small" onClick={() => transition.mutate({ id: order.id, action: 'start' })}>Safarni boshlash</button>}{driver && order.status === 'in_progress' && <button className="button button-dark button-small" onClick={() => transition.mutate({ id: order.id, action: 'complete' })}>Yakunlash</button>}{order.can_cancel && <button className="text-button" onClick={() => transition.mutate({ id: order.id, action: 'cancel' })}>Bekor qilish</button>}</div></article>)}</div></ContentState>
  </>
}

type Plan = ApiItem & { name: string; duration_days: number; price: string | number; description: string }
type Subscription = ApiItem & { plan_name: string; expires_at: string; days_remaining: number; status_display: string; is_active_now: boolean; price_at_purchase: string | number }

export function SubscriptionPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const plans = useQuery({ queryKey: ['subscription-plans'], queryFn: async () => toArray((await api.get<Plan[] | { results: Plan[] }>('/subscriptions/plans/')).data) })
  const active = useQuery({ queryKey: ['active-subscription'], queryFn: async () => (await api.get<Subscription>('/subscriptions/subscriptions/my_active/')).data, retry: false })
  const history = useQuery({ queryKey: ['subscription-history'], queryFn: async () => toArray((await api.get<Subscription[] | { results: Subscription[] }>('/subscriptions/subscriptions/history/')).data) })
  const [notice, setNotice] = useState('')
  const [invoice, setInvoice] = useState<Record<string, unknown> | null>(null)
  const purchase = useMutation({ mutationFn: async (planId: number) => (await api.post<{ subscription: Subscription; payment: ApiItem; invoice: Record<string, unknown> }>('/subscriptions/subscriptions/purchase/', { plan_id: planId, auto_renew: false })).data, onSuccess: (result) => { setInvoice(result.invoice); setNotice(`To‘lov hisobi #${result.payment.id} yaratildi. Obuna provayder to‘lovni tasdiqlagach faollashadi.`); void queryClient.invalidateQueries({ queryKey: ['active-subscription'] }); void queryClient.invalidateQueries({ queryKey: ['subscription-history'] }); void queryClient.invalidateQueries({ queryKey: ['my-payments'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  const cancel = useMutation({ mutationFn: async (id: number) => api.post(`/subscriptions/subscriptions/${id}/cancel/`), onSuccess: () => { setNotice('Obuna bekor qilindi.'); void queryClient.invalidateQueries({ queryKey: ['active-subscription'] }); void queryClient.invalidateQueries({ queryKey: ['subscription-history'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  return <>
    <PageHeading eyebrow="HAYDOVCHI HISOBI" title="Obuna" description="Obuna xaridi backendda to‘lov hisobini yaratadi; faollashuv faqat provayder tasdig‘idan keyin." />
    <div className="notice notice-info"><ShieldCheck size={17} /><p>To‘lov holatini frontend o‘zgartira olmaydi. Obuna server callback orqali faollashtiriladi.</p></div>
    {active.data && <section className="active-subscription"><div className="active-subscription-icon"><BadgeCheck size={22} /></div><div><span className="eyebrow">AMALDAGI OBUNA</span><h2>{active.data.plan_name}</h2><p>{active.data.days_remaining} kun qoldi · {dateTime(active.data.expires_at)}</p></div><StatusBadge value={active.data.status_display} />{user?.driver_profile?.has_active_subscription && <button className="text-button" onClick={() => cancel.mutate(active.data!.id)}>Bekor qilish</button>}</section>}
    {notice && <FormNotice message={notice} />}
    {invoice && <section className="invoice-details"><div><span className="eyebrow">PROVAYDER HISOBI</span><strong>{typeof invoice.reference === 'string' ? invoice.reference : 'Hisob yaratildi'}</strong></div>{typeof invoice.url === 'string' && <a className="button button-dark button-small" href={invoice.url} target="_blank" rel="noreferrer">To‘lov sahifasini ochish <ArrowRight size={14} /></a>}<details><summary>Hisob ma’lumotlari</summary><pre>{JSON.stringify(invoice, null, 2)}</pre></details></section>}
    <div className="section-heading section-heading-spaced"><div><span className="eyebrow">REJALAR</span><h2>Mavjud obunalar</h2></div></div>
    <ContentState loading={plans.isLoading} error={plans.error ? readableError(plans.error) : undefined} empty={plans.data?.length === 0} onRetry={() => void plans.refetch()}><div className="plan-grid">{plans.data?.map((plan) => <article className="plan-item" key={plan.id}><div className="plan-top"><span className="eyebrow">{plan.duration_days} KUN</span><ShieldCheck size={18} /></div><h3>{plan.name}</h3><p>{plan.description}</p><strong>{money(plan.price)}</strong><button className="button button-dark button-wide" disabled={purchase.isPending} onClick={() => purchase.mutate(plan.id)}>Rejani tanlash <ArrowRight size={16} /></button></article>)}</div></ContentState>
    <section className="section-block subscription-history"><div className="section-heading"><div><span className="eyebrow">HISOB TARIXI</span><h2>Obunalar tarixi</h2></div></div><ContentState loading={history.isLoading} error={history.error ? readableError(history.error) : undefined} empty={history.data?.length === 0} onRetry={() => void history.refetch()}><div className="plain-list">{history.data?.map((item) => <div className="plain-row" key={item.id}><span><strong>{item.plan_name}</strong><small>{dateTime(item.expires_at)}</small></span><span>{money(item.price_at_purchase)}</span><StatusBadge value={item.status_display} /></div>)}</div></ContentState></section>
  </>
}

type Payment = ApiItem & { payment_type_display?: string; amount: string | number; status_display?: string; provider_display?: string; created_at?: string; invoice?: unknown }

export function PaymentsPage() {
  const payments = useQuery({ queryKey: ['my-payments'], queryFn: async () => toArray((await api.get<Payment[] | { results: Payment[] }>('/payments/payments/my_payments/')).data) })
  return <>
    <PageHeading eyebrow="HISOB-KITOB" title="To‘lovlar" description="To‘lovlar va hisob-fakturalar. To‘lov tasdig‘i faqat server va provayder orqali amalga oshadi." />
    <div className="notice notice-info"><CreditCard size={17} /><p>To‘lovni qo‘lda tasdiqlash yoki holatini o‘zgartirish mavjud emas. Yangi to‘lov hisobi obuna xaridida yaratiladi.</p></div>
    <ContentState loading={payments.isLoading} error={payments.error ? readableError(payments.error) : undefined} empty={payments.data?.length === 0} onRetry={() => void payments.refetch()}><div className="record-list">{payments.data?.map((payment) => <article className="payment-row" key={payment.id}><span className="payment-symbol"><WalletCards size={19} /></span><div className="payment-copy"><strong>{payment.payment_type_display || 'To‘lov'} · #{payment.id}</strong><span>{payment.provider_display || 'Provayder'} · {dateTime(payment.created_at)}</span></div><strong className="payment-amount">{money(payment.amount)}</strong><StatusBadge value={payment.status_display} /></article>)}</div></ContentState>
  </>
}