import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BadgeCheck, CarFront, CircleAlert, Pencil, Plus, Trash2 } from 'lucide-react'
import { api, readableError, toArray, type ApiItem } from '../api'
import { ContentState, FormNotice, PageHeading, StatusBadge } from '../components/ui'

type VehicleRecord = ApiItem & {
  brand: string
  model: string
  color: string
  plate_number: string
  year: number
  seats_count: number
  seats_for_passengers: number
  is_active: boolean
  is_verified: boolean
  is_usable_for_trip: boolean
  notes?: string
}

type Draft = { brand: string; model: string; color: string; plate_number: string; year: string; seats_count: number; notes: string }
const emptyDraft: Draft = { brand: '', model: '', color: '', plate_number: '', year: String(new Date().getFullYear()), seats_count: 4, notes: '' }
const latestVehicleYear = new Date().getFullYear() + 1

export function VehiclesPage() {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [editing, setEditing] = useState<number | null>(null)
  const [notice, setNotice] = useState('')
  const vehicles = useQuery({ queryKey: ['vehicles'], queryFn: async () => toArray((await api.get<VehicleRecord[] | { results: VehicleRecord[] }>('/vehicles/vehicles/')).data) })
  const save = useMutation({ mutationFn: async () => editing ? api.patch(`/vehicles/vehicles/${editing}/`, { ...draft, year: Number(draft.year) }) : api.post('/vehicles/vehicles/', { ...draft, year: Number(draft.year) }), onSuccess: () => { setDraft(emptyDraft); setEditing(null); setNotice('Avtomobil saqlandi. Tasdiqlash administrator tomonidan amalga oshiriladi.'); void queryClient.invalidateQueries({ queryKey: ['vehicles'] }); void queryClient.invalidateQueries({ queryKey: ['usable-vehicles'] }) }, onError: (cause) => setNotice(readableError(cause)) })
  const action = useMutation({ mutationFn: async ({ id, kind, isActive }: { id: number; kind: 'set_active' | 'delete'; isActive?: boolean }) => kind === 'delete' ? api.delete(`/vehicles/vehicles/${id}/`) : api.post(`/vehicles/vehicles/${id}/set_active/`, { is_active: isActive }), onSuccess: () => { setNotice('Avtomobil holati yangilandi.'); void queryClient.invalidateQueries({ queryKey: ['vehicles'] }); void queryClient.invalidateQueries({ queryKey: ['usable-vehicles'] }) }, onError: (cause) => setNotice(readableError(cause)) })

  function editVehicle(vehicle: VehicleRecord) {
    setEditing(vehicle.id)
    setDraft({ brand: vehicle.brand, model: vehicle.model, color: vehicle.color, plate_number: vehicle.plate_number, year: String(vehicle.year), seats_count: vehicle.seats_count, notes: vehicle.notes || '' })
  }

  return <>
    <PageHeading eyebrow="HAYDOVCHI" title="Avtomobillarim" description="Avtomobil ma’lumotlari, faollik va tasdiqlash holati. Haydovchi faqat o‘z avtomobillarini boshqaradi." />
    <div className="notice notice-info"><BadgeCheck size={17} /><p>Tasdiqlashni faqat administrator amalga oshiradi. Yangi yoki tahrirlangan avtomobil tasdiqlanmaguncha yo‘lovga biriktirilmaydi.</p></div>
    <form className="inline-create-form" onSubmit={(event) => { event.preventDefault(); setNotice(''); save.mutate() }}><div className="form-title-row"><div><span className="eyebrow">AVTOMOBIL</span><h2>{editing ? `#${editing} tahrirlash` : 'Avtomobil qo‘shish'}</h2></div><CarFront size={20} /></div><div className="field-row"><label>Brend<input required maxLength={60} value={draft.brand} onChange={(event) => setDraft({ ...draft, brand: event.target.value })} placeholder="Chevrolet" /></label><label>Model<input required maxLength={60} value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="Cobalt" /></label></div><div className="field-row"><label>Rang<input required maxLength={40} value={draft.color} onChange={(event) => setDraft({ ...draft, color: event.target.value })} placeholder="Oq" /></label><label>Davlat raqami<input required maxLength={15} value={draft.plate_number} onChange={(event) => setDraft({ ...draft, plate_number: event.target.value.toUpperCase() })} placeholder="01 A 123 BC" /></label></div><div className="field-row"><label>Ishlab chiqarilgan yil<input type="number" min={1990} max={latestVehicleYear} required value={draft.year} onChange={(event) => setDraft({ ...draft, year: event.target.value })} /></label><label>Jami o‘rindiqlar<input type="number" min={1} max={20} required value={draft.seats_count} onChange={(event) => setDraft({ ...draft, seats_count: Number(event.target.value) })} /></label></div><label>Izoh <span className="optional-label">ixtiyoriy</span><input value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} maxLength={255} /></label>{notice && <FormNotice message={notice} />}<div className="record-actions"><button className="button button-dark" disabled={save.isPending}><Plus size={16} />{save.isPending ? 'Saqlanmoqda…' : editing ? 'O‘zgarishlarni saqlash' : 'Avtomobil qo‘shish'}</button>{editing && <button type="button" className="button button-outline" onClick={() => { setEditing(null); setDraft(emptyDraft) }}>Bekor qilish</button>}</div></form>
    <div className="section-heading section-heading-spaced"><div><span className="eyebrow">TRANSPORT</span><h2>Ro‘yxatdagi avtomobillar</h2></div></div>
    <ContentState loading={vehicles.isLoading} error={vehicles.error ? readableError(vehicles.error) : undefined} empty={vehicles.data?.length === 0} onRetry={() => void vehicles.refetch()}><div className="record-list">{vehicles.data?.map((vehicle) => <article className="record-card vehicle-card" key={vehicle.id}><div className="vehicle-illustration"><CarFront size={25} /></div><div className="vehicle-copy"><div className="record-top"><span className="record-id">AVTOMOBIL #{vehicle.id}</span><StatusBadge value={vehicle.is_verified ? 'verified' : 'pending'} /></div><h3>{vehicle.brand} {vehicle.model}</h3><p>{vehicle.color} · {vehicle.year} · {vehicle.plate_number}</p><span className="vehicle-seat-count">{vehicle.seats_for_passengers} yo‘lovchi o‘rni · {vehicle.is_usable_for_trip ? 'Yo‘lovga tayyor' : 'Yo‘lovga yaroqsiz'}</span><div className="record-actions"><button className="button button-outline button-small" onClick={() => editVehicle(vehicle)}><Pencil size={14} />Tahrirlash</button><button className="button button-outline button-small" onClick={() => action.mutate({ id: vehicle.id, kind: 'set_active', isActive: !vehicle.is_active })}>{vehicle.is_active ? 'Faolsizlantirish' : 'Faollashtirish'}</button><button className="icon-button danger-icon" onClick={() => { if (window.confirm('Avtomobilni o‘chirasizmi?')) action.mutate({ id: vehicle.id, kind: 'delete' }) }} aria-label="Avtomobilni o‘chirish"><Trash2 size={16} /></button><span className="vehicle-active-state"><i className={vehicle.is_active ? 'active-dot' : ''} />{vehicle.is_active ? 'Faol' : 'Faol emas'}</span></div></div></article>)}</div></ContentState>
    {action.error && <p className="inline-error"><CircleAlert size={15} />{readableError(action.error)}</p>}
  </>
}