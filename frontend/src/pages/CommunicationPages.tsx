import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Check, CircleAlert, Headphones, MessageCircle, Send, Star } from 'lucide-react'
import { api, dateTime, readableError, toArray, type ApiItem, type Order } from '../api'
import { ContentState, EmptyState, FormNotice, PageHeading, StatusBadge } from '../components/ui'

type Notice = ApiItem & { title?: string; message?: string; is_read?: boolean; created_at?: string; type?: string }
type Thread = ApiItem & { order_id: number; counterpart_name?: string; unread_count?: number; last_message?: { text?: string }; is_closed?: boolean }
type ChatMessage = ApiItem & { text: string; is_mine: boolean; sender_name?: string; created_at?: string }
type Ticket = ApiItem & { subject: string; category: string; status: string; status_display?: string; created_at?: string }
type SupportMessage = ApiItem & { body: string; is_mine?: boolean; is_from_support?: boolean; sender_name?: string; created_at?: string }
type Review = ApiItem & { reviewed_user_name?: string; reviewer_name?: string; rating: number; comment?: string; created_at?: string }

export function NotificationsPage() {
  const queryClient = useQueryClient()
  const notifications = useQuery({ queryKey: ['notifications'], queryFn: async () => toArray((await api.get<Notice[] | { results: Notice[] }>('/notifications/notifications/')).data) })
  const markRead = useMutation({ mutationFn: async (payload: { mark_all?: boolean; notification_ids?: number[] }) => api.post('/notifications/notifications/mark_read/', payload), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['notifications'] }); void queryClient.invalidateQueries({ queryKey: ['notifications-unread'] }) } })
  return <>
    <PageHeading eyebrow="ALOQA" title="Bildirishnomalar" description="Safar, buyurtma va hisobingiz bo‘yicha xabarlar." action={<button className="button button-outline" onClick={() => markRead.mutate({ mark_all: true })} disabled={markRead.isPending}><Check size={16} />Barchasini o‘qilgan</button>} />
    {markRead.error && <p className="inline-error"><CircleAlert size={15} />{readableError(markRead.error)}</p>}
    <ContentState loading={notifications.isLoading} error={notifications.error ? readableError(notifications.error) : undefined} empty={notifications.data?.length === 0} onRetry={() => void notifications.refetch()}><div className="notification-list">{notifications.data?.map((notice) => <article className={`notification-item ${notice.is_read ? '' : 'notification-unread'}`} key={notice.id}><span className="notification-icon"><Bell size={18} /></span><div className="notification-copy"><div><strong>{notice.title || 'TezTaxiTop xabari'}</strong><StatusBadge value={notice.type} /></div><p>{notice.message}</p><time>{dateTime(notice.created_at)}</time></div>{!notice.is_read && <button className="icon-button" onClick={() => markRead.mutate({ notification_ids: [notice.id] })} aria-label="O‘qilgan deb belgilash"><Check size={17} /></button>}</article>)}</div></ContentState>
  </>
}

export function ChatPage() {
  const location = useLocation()
  const navOrderId = (location.state as { orderId?: number } | null)?.orderId ?? null
  const queryClient = useQueryClient()
  const [orderId, setOrderId] = useState<number | null>(navOrderId)
  const [text, setText] = useState('')

  useEffect(() => {
    if (navOrderId) {
      setOrderId(navOrderId)
    }
  }, [navOrderId])
  const threads = useQuery({ queryKey: ['chat-threads'], queryFn: async () => toArray((await api.get<Thread[] | { results: Thread[] }>('/chat/chats/')).data) })
  const messages = useQuery({ queryKey: ['chat-messages', orderId], enabled: Boolean(orderId), refetchInterval: 8000, queryFn: async () => {
    const previous = queryClient.getQueryData<{ results: ChatMessage[]; next_after_id: number; is_closed: boolean }>(['chat-messages', orderId])
    const after = previous?.next_after_id || 0
    const { data } = await api.get<{ results: ChatMessage[]; next_after_id: number; is_closed: boolean }>(`/chat/chats/${orderId}/messages/?after=${after}`)
    return { ...data, results: [...(previous?.results ?? []), ...data.results] }
  } })
  const send = useMutation({ mutationFn: async () => api.post(`/chat/chats/${orderId}/messages/`, { text, type: 'text' }), onSuccess: () => { setText(''); void queryClient.invalidateQueries({ queryKey: ['chat-messages', orderId] }); void queryClient.invalidateQueries({ queryKey: ['chat-threads'] }) } })
  return <>
    <PageHeading eyebrow="ALOQA" title="Chat" description="Buyurtma ishtirokchilari bilan xavfsiz yozishmalar." />
    <div className="chat-layout"><aside className="chat-thread-list"><span className="eyebrow">SUHBATLAR</span><ContentState loading={threads.isLoading} error={threads.error ? readableError(threads.error) : undefined} empty={threads.data?.length === 0} onRetry={() => void threads.refetch()}><div className="thread-items">{threads.data?.map((thread) => <button className={`thread-item ${orderId === thread.order_id ? 'thread-active' : ''}`} key={thread.id} onClick={() => setOrderId(thread.order_id)}><span className="thread-avatar">{thread.counterpart_name?.charAt(0) || 'T'}</span><span><strong>{thread.counterpart_name || `Buyurtma #${thread.order_id}`}</strong><small>{thread.last_message?.text || `Buyurtma #${thread.order_id}`}</small></span>{Boolean(thread.unread_count) && <i className="unread-dot" />}</button>)}</div></ContentState></aside>
      <section className="chat-window">{!orderId ? <EmptyState icon={MessageCircle} title="Suhbat tanlanmagan" description="Xabarlarni ochish uchun chap tomondan buyurtmani tanlang." /> : <><div className="chat-topline"><span className="thread-avatar"><MessageCircle size={18} /></span><div><strong>{threads.data?.find((item) => item.order_id === orderId)?.counterpart_name || `Buyurtma #${orderId}`}</strong><small>Buyurtma bo‘yicha suhbat</small></div></div><ContentState loading={messages.isLoading} error={messages.error ? readableError(messages.error) : undefined} empty={messages.data?.results.length === 0} onRetry={() => void messages.refetch()}><div className="chat-messages">{messages.data?.results.map((message) => <div className={`chat-bubble ${message.is_mine ? 'chat-mine' : ''}`} key={message.id}><p>{message.text}</p><time>{dateTime(message.created_at)}</time></div>)}</div></ContentState>{messages.data?.is_closed ? <div className="chat-closed">Bu suhbat yopilgan.</div> : <form className="chat-compose" onSubmit={(event) => { event.preventDefault(); if (text.trim()) send.mutate() }}><input aria-label="Xabar matni" value={text} onChange={(event) => setText(event.target.value)} placeholder="Xabar yozing…" maxLength={2000} /><button className="button button-dark icon-submit" disabled={send.isPending || !text.trim()} aria-label="Xabar yuborish"><Send size={17} /></button></form>}{send.error && <p className="inline-error"><CircleAlert size={15} />{readableError(send.error)}</p>}</>}</section></div>
  </>
}

export function ReviewsPage() {
  const queryClient = useQueryClient()
  const [reviewTab, setReviewTab] = useState<'given' | 'received'>('given')
  const [editingReview, setEditingReview] = useState<Review | null>(null)
  const [orderId, setOrderId] = useState('')
  const [rating, setRating] = useState(5)
  const [comment, setComment] = useState('')
  const [notice, setNotice] = useState('')
  const reviewable = useQuery({ queryKey: ['reviewable-orders'], queryFn: async () => toArray((await api.get<Order[] | { results: Order[] }>('/orders/reviewable-orders/')).data) })
  const reviews = useQuery({ queryKey: ['reviews', reviewTab], queryFn: async () => toArray((await api.get<Review[] | { results: Review[] }>(`/reviews/reviews/${reviewTab}/`)).data) })
  const summary = useQuery({ queryKey: ['rating-summary'], queryFn: async () => (await api.get<{ cached_rating?: string; rating_count?: number }>('/reviews/rating-summary/')).data })
  const create = useMutation({ mutationFn: async () => editingReview ? api.patch(`/reviews/reviews/${editingReview.id}/`, { rating, comment }) : api.post('/reviews/reviews/', { order_id: Number(orderId), rating, comment }), onSuccess: () => { setNotice(editingReview ? 'Baho yangilandi.' : 'Baho yuborildi.'); setOrderId(''); setComment(''); setEditingReview(null); void queryClient.invalidateQueries({ queryKey: ['reviewable-orders'] }); void queryClient.invalidateQueries({ queryKey: ['reviews'] }); void queryClient.invalidateQueries({ queryKey: ['rating-summary'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  const removeReview = useMutation({ mutationFn: async (id: number) => api.delete(`/reviews/reviews/${id}/`), onSuccess: () => { setNotice('Baho o‘chirildi.'); void queryClient.invalidateQueries({ queryKey: ['reviews'] }); void queryClient.invalidateQueries({ queryKey: ['rating-summary'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  return <>
    <PageHeading eyebrow="ISHONCH VA SIFAT" title="Baholar" description="Faqat yakunlangan buyurtma ishtirokchilari bir-birini baholashi mumkin." />
    <div className="rating-summary"><span className="rating-summary-star"><Star size={21} fill="currentColor" /></span><strong>{summary.data?.cached_rating || '—'}</strong><span>Haydovchi reytingi · {summary.data?.rating_count ?? 0} ta baho</span></div>
    <form className="inline-create-form review-form" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><div className="form-title-row"><div><span className="eyebrow">{editingReview ? `BAHO #${editingReview.id}` : 'YANGI BAHO'}</span><h2>{editingReview ? 'Bahoni tahrirlash' : 'Safarni baholang'}</h2></div><Star size={20} /></div>{!editingReview && <label>Yakunlangan buyurtma<select value={orderId} onChange={(event) => setOrderId(event.target.value)} required><option value="">Buyurtmani tanlang</option>{reviewable.data?.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.trip_route || 'Safar'} · {item.driver_name}</option>)}</select></label>}<fieldset className="rating-control"><legend>Baho</legend>{[1, 2, 3, 4, 5].map((value) => <button type="button" key={value} className={value <= rating ? 'rating-on' : ''} onClick={() => setRating(value)} aria-label={`${value} yulduz`}><Star size={24} fill={value <= rating ? 'currentColor' : 'none'} /></button>)}</fieldset><label>Izoh <span className="optional-label">ixtiyoriy</span><textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} maxLength={1000} /></label>{notice && <FormNotice message={notice} />}<div className="record-actions"><button className="button button-dark" disabled={create.isPending || (!editingReview && !orderId)}><Star size={16} />{editingReview ? 'O‘zgarishlarni saqlash' : 'Bahoni yuborish'}</button>{editingReview && <button type="button" className="button button-outline" onClick={() => { setEditingReview(null); setRating(5); setComment('') }}>Bekor qilish</button>}</div></form>
    <div className="section-heading section-heading-spaced"><div><span className="eyebrow">BAHOLAR</span><h2>{reviewTab === 'given' ? 'Yuborgan baholarim' : 'Menga berilgan baholar'}</h2></div><div className="tab-control"><button className={reviewTab === 'given' ? 'tab-active' : ''} onClick={() => setReviewTab('given')}>Yuborgan</button><button className={reviewTab === 'received' ? 'tab-active' : ''} onClick={() => setReviewTab('received')}>Qabul qilingan</button></div></div><ContentState loading={reviews.isLoading} error={reviews.error ? readableError(reviews.error) : undefined} empty={reviews.data?.length === 0} onRetry={() => void reviews.refetch()}><div className="record-list">{reviews.data?.map((review) => <article className="review-item" key={review.id}><span className="review-star"><Star size={18} fill="currentColor" /></span><div><strong>{reviewTab === 'given' ? review.reviewed_user_name : review.reviewer_name || `Foydalanuvchi #${review.id}`}</strong><span className="rating-stars">{'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}</span><p>{review.comment || 'Izoh qoldirilmagan'}</p><small>{dateTime(review.created_at)}</small>{reviewTab === 'given' && <div className="record-actions"><button className="text-button" onClick={() => { setEditingReview(review); setRating(review.rating); setComment(review.comment || ''); setNotice(''); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>Tahrirlash</button><button className="text-button" onClick={() => { if (window.confirm('Bahoni o‘chirasizmi?')) removeReview.mutate(review.id) }}>O‘chirish</button></div>}</div><span className="review-score">{review.rating}.0</span></article>)}</div></ContentState>
  </>
}

const categories = ['payment', 'subscription', 'ride', 'verification', 'account', 'technical', 'other']

export function SupportPage() {
  const queryClient = useQueryClient()
  const [ticketId, setTicketId] = useState<number | null>(null)
  const [subject, setSubject] = useState('')
  const [category, setCategory] = useState('other')
  const [body, setBody] = useState('')
  const [reply, setReply] = useState('')
  const [notice, setNotice] = useState('')
  const tickets = useQuery({ queryKey: ['support-tickets'], queryFn: async () => toArray((await api.get<Ticket[] | { results: Ticket[] }>('/support/support/')).data) })
  const messages = useQuery({ queryKey: ['support-messages', ticketId], enabled: Boolean(ticketId), queryFn: async () => toArray((await api.get<SupportMessage[] | { results: SupportMessage[] }>(`/support/support/${ticketId}/messages/`)).data) })
  const create = useMutation({ mutationFn: async () => api.post<Ticket>('/support/support/', { subject, category, body }), onSuccess: ({ data }) => { setTicketId(data.id); setSubject(''); setBody(''); setNotice('Murojaat yuborildi.'); void queryClient.invalidateQueries({ queryKey: ['support-tickets'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  const send = useMutation({ mutationFn: async () => api.post(`/support/support/${ticketId}/messages/`, { body: reply }), onSuccess: () => { setReply(''); void queryClient.invalidateQueries({ queryKey: ['support-messages', ticketId] }); void queryClient.invalidateQueries({ queryKey: ['support-tickets'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  return <>
    <PageHeading eyebrow="ALOQA" title="Yordam markazi" description="Savol yoki muammo bo‘yicha murojaat yarating. Javoblar shu yerda ko‘rinadi." />
    <div className="support-layout"><section className="support-left"><form className="inline-create-form" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><div className="form-title-row"><div><span className="eyebrow">YANGI MUROJAAT</span><h2>Qanday yordam kerak?</h2></div><Headphones size={20} /></div><label>Mavzu<input value={subject} onChange={(event) => setSubject(event.target.value)} maxLength={200} required placeholder="Muammo qisqacha" /></label><label>Yo‘nalish<select value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option value={item} key={item}>{item}</option>)}</select></label><label>Xabar<textarea value={body} onChange={(event) => setBody(event.target.value)} rows={4} maxLength={4000} required placeholder="Muammoni batafsil tushuntiring" /></label>{notice && <FormNotice message={notice} />}<button className="button button-dark" disabled={create.isPending}><MessageCircle size={16} />Murojaat yuborish</button></form>
      <section className="section-block"><div className="section-heading"><div><span className="eyebrow">MUROJAATLAR</span><h2>Yaqindagi murojaatlar</h2></div></div><ContentState loading={tickets.isLoading} error={tickets.error ? readableError(tickets.error) : undefined} empty={tickets.data?.length === 0} onRetry={() => void tickets.refetch()}><div className="plain-list">{tickets.data?.map((ticket) => <button className={`ticket-row ${ticket.id === ticketId ? 'ticket-selected' : ''}`} key={ticket.id} onClick={() => setTicketId(ticket.id)}><span><strong>{ticket.subject}</strong><small>#{ticket.id} · {ticket.category} · {dateTime(ticket.created_at)}</small></span><StatusBadge value={ticket.status_display || ticket.status} /></button>)}</div></ContentState></section></section>
      <section className="support-conversation"><div className="section-heading"><div><span className="eyebrow">MUROJAAT SUHBATI</span><h2>{ticketId ? `#${ticketId} bo‘yicha` : 'Murojaat tanlang'}</h2></div></div>{!ticketId ? <EmptyState icon={Headphones} title="Hozircha suhbat yo‘q" description="Murojaat tanlang yoki yangi murojaat yuboring." /> : <><ContentState loading={messages.isLoading} error={messages.error ? readableError(messages.error) : undefined} empty={messages.data?.length === 0} onRetry={() => void messages.refetch()}><div className="support-messages">{messages.data?.map((item) => <article className={`support-message ${item.is_mine ? 'support-message-mine' : ''}`} key={item.id}><strong>{item.sender_name || (item.is_from_support ? 'Yordam xizmati' : 'Siz')}</strong><p>{item.body}</p><time>{dateTime(item.created_at)}</time></article>)}</div></ContentState><form className="chat-compose" onSubmit={(event) => { event.preventDefault(); if (reply.trim()) send.mutate() }}><input value={reply} onChange={(event) => setReply(event.target.value)} maxLength={4000} placeholder="Javob yozing…" /><button className="button button-dark icon-submit" disabled={send.isPending || !reply.trim()} aria-label="Javob yuborish"><Send size={17} /></button></form></>}</section></div>
  </>
}