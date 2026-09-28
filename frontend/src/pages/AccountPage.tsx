import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BadgeCheck, CircleAlert, Languages, Phone, Save, ShieldCheck, UserRound } from 'lucide-react'
import { api, readableError, type User } from '../api'
import { useAuth } from '../authContext'
import { FormNotice, PageHeading } from '../components/ui'

type Section = 'profile' | 'onboarding' | 'settings'

export function AccountPage({ section }: { section: Section }) {
  const { user, setUser } = useAuth()
  const [firstName, setFirstName] = useState(user?.first_name ?? '')
  const [lastName, setLastName] = useState(user?.last_name ?? '')
  const [language, setLanguage] = useState(user?.language_code ?? 'uz')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const profile = useQuery({ queryKey: ['my-driver-profile'], queryFn: async () => (await api.get('/my-driver-profile/')).data, enabled: Boolean(user?.driver_profile) })
  const botUsername = import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined

  async function saveProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true); setMessage(''); setError('')
    try {
      const { data } = await api.patch<User>('/auth/me/', { first_name: firstName, last_name: lastName, language_code: language })
      setUser(data); setMessage('Profil saqlandi.')
    } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }

  async function changeRole(role: User['role']) {
    setBusy(true); setError(''); setMessage('')
    try {
      const { data } = await api.patch<User>('/auth/me/role/', { role })
      setUser(data)
      localStorage.setItem('teztaxitop_mode', role === 'driver' ? 'driver' : 'passenger')
      window.dispatchEvent(new Event('teztaxitop-mode-change'))
      setMessage(`Rol yangilandi: ${data.role_display}.`)
    } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }

  const heading = section === 'profile' ? ['HISOB', 'Profil', 'Shaxsiy ma’lumotlaringiz va haydovchi profilingiz.'] : section === 'settings' ? ['TIZIM', 'Sozlamalar', 'Til va ilova hisobini boshqarish.'] : ['BOSHLASH', 'Ro‘yxatdan o‘tish', 'Telegram hisobi backend orqali aniqlangan. Rolni tanlang va telefonni botda tasdiqlang.']

  return <>
    <PageHeading eyebrow={heading[0]} title={heading[1]} description={heading[2]} />
    {section === 'onboarding' && <div className="onboarding-band"><span className="onboarding-icon"><ShieldCheck size={23} /></span><div><strong>Telegram hisobiga ulangan</strong><p>Telegram ID: {user?.telegram_id ?? 'Mavjud emas'} · Profil holati serverdan olindi</p></div><BadgeCheck size={20} /></div>}
    <div className="account-grid">
      {(section === 'profile' || section === 'onboarding') && <section className="form-section"><div className="section-heading"><div><span className="eyebrow">SHAXSIY MA’LUMOT</span><h2>Profil tafsilotlari</h2></div><UserRound size={20} /></div>
        <form className="stack-form" onSubmit={saveProfile}><div className="field-row"><label>Ism<input value={firstName} onChange={(event) => setFirstName(event.target.value)} maxLength={150} /></label><label>Familiya<input value={lastName} onChange={(event) => setLastName(event.target.value)} maxLength={150} /></label></div><label>Til<select value={language} onChange={(event) => setLanguage(event.target.value)}><option value="uz">O‘zbekcha</option><option value="ru">Русский</option><option value="en">English</option></select></label><FormNotice message={message} />{error && <p className="inline-error"><CircleAlert size={15} />{error}</p>}<button className="button button-dark" disabled={busy}><Save size={16} />{busy ? 'Saqlanmoqda…' : 'Profilni saqlash'}</button></form>
      </section>}
      {(section === 'profile' || section === 'onboarding') && <section className="form-section"><div className="section-heading"><div><span className="eyebrow">TELEGRAM BOG‘LANISHI</span><h2>Telefon raqami</h2></div><Phone size={20} /></div><div className="phone-readonly"><span className="phone-symbol"><Phone size={18} /></span><div><strong>{user?.phone_number || 'Hali ulanmagan'}</strong><span>{user?.phone_number ? 'Backend profilidan o‘qildi' : 'Telegram botda kontakt yuboring'}</span></div><span className={`phone-state ${user?.phone_number ? 'phone-verified' : ''}`}>{user?.phone_number ? 'Tasdiqlangan' : 'Kutilmoqda'}</span></div><div className="notice notice-info"><ShieldCheck size={17} /><p>Telefon raqami faqat Telegram botning “Kontaktni yuborish” tugmasi orqali tasdiqlanadi. Bu yerda tahrirlash o‘chirilgan.</p></div>{botUsername && <a className="button button-outline" href={`https://t.me/${botUsername}`} target="_blank" rel="noreferrer">Botni ochish <ArrowRight size={16} /></a>}
        {user?.driver_profile && <div className="driver-summary"><div><span className="eyebrow">HAYDOVCHI PROFILI</span><strong>{user.driver_profile.is_verified ? 'Tasdiqlangan haydovchi' : 'Tasdiq kutilmoqda'}</strong></div><span className={`status-badge ${user.driver_profile.is_verified ? 'status-positive' : 'status-pending'}`}><i />{user.driver_profile.is_verified ? 'Tasdiqlangan' : 'Tekshiruvda'}</span><p>Reyting {user.driver_profile.rating} · {user.driver_profile.completed_trips} ta yakunlangan safar</p></div>}
      </section>}
      {(section === 'settings' || section === 'onboarding') && <section className="form-section"><div className="section-heading"><div><span className="eyebrow">FOYDALANISH REJIMI</span><h2>Rolni tanlash</h2></div><Languages size={20} /></div><p className="form-intro">Rollar backend orqali saqlanadi. “Ikkalasi” roli ilovada yo‘lovchi va haydovchi rejimlari orasida almashish imkonini beradi.</p><div className="role-options">{(['passenger', 'driver', 'both'] as const).map((role) => <button key={role} className={`role-option ${user?.role === role ? 'role-selected' : ''}`} disabled={busy} onClick={() => void changeRole(role)}><span>{role === 'passenger' ? 'Yo‘lovchi' : role === 'driver' ? 'Haydovchi' : 'Ikkalasi'}</span><small>{role === 'passenger' ? 'Safar so‘rovlari va buyurtmalar' : role === 'driver' ? 'Yo‘lovlar va haydovchi buyurtmalari' : 'Ikkala rejimdan foydalanish'}</small><i>{user?.role === role ? 'Tanlangan' : 'Tanlash'}</i></button>)}</div><FormNotice message={message} />{error && <p className="inline-error"><CircleAlert size={15} />{error}</p>}<div className="notice notice-warning"><CircleAlert size={17} /><p>Haydovchi bo‘lish uchun backend tasdig‘i, faol obuna va tasdiqlangan avtomobil talab qilinishi mumkin.</p></div></section>}
      {section === 'settings' && <section className="form-section"><div className="section-heading"><div><span className="eyebrow">XAVFSIZLIK</span><h2>Hisob holati</h2></div><ShieldCheck size={20} /></div><div className="settings-line"><span>Telegram ID</span><strong>{user?.telegram_id ?? '—'}</strong></div><div className="settings-line"><span>Hisob roli</span><strong>{user?.role_display}</strong></div><div className="settings-line"><span>Haydovchi tekshiruvi</span><strong>{profile.data?.is_verified ? 'Tasdiqlangan' : user?.driver_profile ? 'Kutilmoqda' : 'Haydovchi emas'}</strong></div><div className="notice notice-info"><Languages size={17} /><p>Interfeys tili profil bilan birga backendda saqlanadi.</p></div></section>}
    </div>
  </>
}