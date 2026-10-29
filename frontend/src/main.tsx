import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type User = { id: string; email: string; role: 'USER' | 'ADMIN' }
type Room = { id: string; name: string; capacity: number; price_per_30min_kopeks: number; is_active: boolean }
type Booking = { id: string; room_id: string; title: string; booking_date: string; start_time: string; end_time: string; duration_minutes: number; attendees: number; total_price_kopeks: number; status: string; expires_at: string }
type ApiError = { error?: { code: string; message: string; fields?: { field: string; message: string }[] } }
type FieldErrors = Record<string, string>
type Page = 'rooms' | 'book' | 'bookings' | 'admin'

const statusLabels: Record<string, string> = {
  CREATED: 'Ожидает оплаты', PAYMENT_PENDING: 'Оплата обрабатывается',
  CONFIRMED: 'Подтверждена', PAYMENT_FAILED: 'Оплата отклонена',
  CANCELLED: 'Отменена', EXPIRED: 'Срок истёк'
}
const money = (kopeks: number) => `${(kopeks / 100).toLocaleString('ru-RU')} ₽`

async function api<T>(path: string, token: string | null, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {})
    },
    body: body !== undefined ? JSON.stringify(body) : undefined
  })
  if (!response.ok) throw await response.json() as ApiError
  return response.json() as Promise<T>
}

function useFeedback() {
  const [fields, setFields] = useState<FieldErrors>({})
  const [message, setMessage] = useState('')
  const clear = () => { setFields({}); setMessage('') }
  const clearField = (field: string) => setFields(previous => {
    if (!previous[field]) return previous
    const next = { ...previous }
    delete next[field]
    return next
  })
  const validate = (errors: FieldErrors) => {
    setFields(errors)
    setMessage('')
    return Object.keys(errors).length === 0
  }
  const fromApi = (cause: unknown) => {
    const error = (cause as ApiError)?.error
    if (error?.fields?.length) {
      setFields(Object.fromEntries(error.fields.map(item => [item.field, item.message])))
      setMessage('')
    } else {
      setMessage(error?.message || 'Не удалось выполнить запрос')
    }
  }
  return { fields, message, clear, clearField, validate, fromApi }
}

function FieldError({ id, testId, message }: { id: string; testId: string; message?: string }) {
  return message ? <small id={id} data-testid={testId} className="field-error" role="alert">{message}</small> : null
}

function FormError({ message }: { message: string }) {
  return message ? <p className="error" data-testid="form-error" role="alert">{message}</p> : null
}

function validateEmailPassword(email: string, password: string, mode: 'login' | 'register'): FieldErrors {
  const errors: FieldErrors = {}
  const normalized = email.trim()
  if (!normalized) errors.email = 'Введите email'
  else if (normalized.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) errors.email = 'Введите корректный email до 254 символов'
  if (!password) errors.password = 'Введите пароль'
  else if (mode === 'register' && (password.length < 8 || password.length > 64)) errors.password = 'Пароль должен содержать от 8 до 64 символов'
  return errors
}

function validateRoom(name: string, capacity: string, price: string): FieldErrors {
  const errors: FieldErrors = {}
  if (name.trim().length < 3 || name.trim().length > 50) errors.name = 'Название должно содержать от 3 до 50 символов'
  const capacityNumber = Number(capacity)
  if (!capacity || !Number.isInteger(capacityNumber) || capacityNumber < 2 || capacityNumber > 10) errors.capacity = 'Вместимость: целое число от 2 до 10'
  const priceNumber = Number(price)
  if (!price || !Number.isInteger(priceNumber) || priceNumber < 10000 || priceNumber > 200000) errors.price_per_30min_kopeks = 'Цена: целое число от 10000 до 200000 копеек'
  return errors
}

function moscowToday(): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}

function validateBooking(title: string, date: string, start: string, duration: number, attendees: string, capacity: number): FieldErrors {
  const errors: FieldErrors = {}
  if (title.trim().length < 3 || title.trim().length > 60) errors.title = 'Название встречи должно содержать от 3 до 60 символов'
  if (!validDate(date)) errors.booking_date = 'Выберите дату в формате ГГГГ-ММ-ДД'
  else {
    const today = moscowToday()
    const lastDay = new Date(`${today}T00:00:00Z`)
    lastDay.setUTCDate(lastDay.getUTCDate() + 14)
    const weekday = new Date(`${date}T00:00:00Z`).getUTCDay()
    if (date <= today || date > lastDay.toISOString().slice(0, 10) || weekday === 0 || weekday === 6) {
      errors.booking_date = 'Выберите будний день с завтра по следующие 14 дней'
    }
  }
  const timeMatch = /^(\d{2}):(\d{2})$/.exec(start)
  const startMinutes = timeMatch ? Number(timeMatch[1]) * 60 + Number(timeMatch[2]) : -1
  if (!timeMatch || !['00', '30'].includes(timeMatch[2]) || startMinutes < 540 || startMinutes > 1230) {
    errors.start_time = 'Начало: с 09:00 до 20:30, шаг 30 минут'
  }
  if (![30, 60, 90, 120].includes(duration)) errors.duration_minutes = 'Выберите длительность 30, 60, 90 или 120 минут'
  else if (!errors.start_time && startMinutes + duration > 1260) errors.duration_minutes = 'Бронь должна закончиться до 21:00'
  const count = Number(attendees)
  if (!attendees || !Number.isInteger(count) || count < 1 || count > capacity) errors.attendees = `Укажите от 1 до ${capacity} участников`
  return errors
}

function RoomEditor({ room, onSave }: { room: Room; onSave: (patch: Partial<Room>) => Promise<void> }) {
  const [name, setName] = useState(room.name)
  const [capacity, setCapacity] = useState(String(room.capacity))
  const [price, setPrice] = useState(String(room.price_per_30min_kopeks))
  const [active, setActive] = useState(room.is_active)
  const [busy, setBusy] = useState(false)
  const feedback = useFeedback()

  useEffect(() => {
    setName(room.name)
    setCapacity(String(room.capacity))
    setPrice(String(room.price_per_30min_kopeks))
    setActive(room.is_active)
  }, [room])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!feedback.validate(validateRoom(name, capacity, price))) return
    setBusy(true)
    try {
      await onSave({ name: name.trim(), capacity: Number(capacity), price_per_30min_kopeks: Number(price), is_active: active })
      feedback.clear()
    } catch (cause) { feedback.fromApi(cause) }
    finally { setBusy(false) }
  }

  return <article className="panel" data-testid={`room-editor-${room.id}`}>
    <h3>{room.name}</h3>
    <form noValidate onSubmit={submit} data-testid={`room-edit-form-${room.id}`}>
      <label>Название
        <input data-testid="room-edit-name" value={name} aria-invalid={Boolean(feedback.fields.name)} aria-describedby={feedback.fields.name ? `room-edit-name-error-${room.id}` : undefined} onChange={event => { setName(event.target.value); feedback.clearField('name') }} />
        <FieldError id={`room-edit-name-error-${room.id}`} testId="room-edit-name-error" message={feedback.fields.name} />
      </label>
      <label>Вместимость
        <input data-testid="room-edit-capacity" type="number" value={capacity} aria-invalid={Boolean(feedback.fields.capacity)} aria-describedby={feedback.fields.capacity ? `room-edit-capacity-error-${room.id}` : undefined} onChange={event => { setCapacity(event.target.value); feedback.clearField('capacity') }} />
        <FieldError id={`room-edit-capacity-error-${room.id}`} testId="room-edit-capacity-error" message={feedback.fields.capacity} />
      </label>
      <label>Цена за 30 минут, копейки
        <input data-testid="room-edit-price" type="number" value={price} aria-invalid={Boolean(feedback.fields.price_per_30min_kopeks)} aria-describedby={feedback.fields.price_per_30min_kopeks ? `room-edit-price-error-${room.id}` : undefined} onChange={event => { setPrice(event.target.value); feedback.clearField('price_per_30min_kopeks') }} />
        <FieldError id={`room-edit-price-error-${room.id}`} testId="room-edit-price-error" message={feedback.fields.price_per_30min_kopeks} />
      </label>
      <label className="checkbox"><input data-testid="room-edit-active" type="checkbox" checked={active} onChange={event => setActive(event.target.checked)} /> Активна</label>
      <button data-testid="room-edit-submit" type="submit" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить'}</button>
      <FormError message={feedback.message} />
    </form>
  </article>
}

function App() {
  const [token, setToken] = useState<string | null>(localStorage.getItem('bookinglab_token'))
  const [user, setUser] = useState<User | null>(null)
  const [page, setPage] = useState<Page>('rooms')
  const [rooms, setRooms] = useState<Room[]>([])
  const [bookings, setBookings] = useState<Booking[]>([])
  const [selected, setSelected] = useState<Room | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [start, setStart] = useState('09:00')
  const [duration, setDuration] = useState(30)
  const [attendees, setAttendees] = useState('1')
  const [paymentMessage, setPaymentMessage] = useState('')
  const [roomName, setRoomName] = useState('')
  const [roomCapacity, setRoomCapacity] = useState('2')
  const [roomPrice, setRoomPrice] = useState('30000')
  const authFeedback = useFeedback()
  const bookingFeedback = useFeedback()
  const roomFeedback = useFeedback()
  const actionFeedback = useFeedback()

  function logout() {
    localStorage.removeItem('bookinglab_token')
    setToken(null); setUser(null); setPage('rooms'); setAuthMode('login'); setPassword('')
    authFeedback.clear(); bookingFeedback.clear(); roomFeedback.clear(); actionFeedback.clear()
  }

  useEffect(() => { if (token) api<User>('/users/me', token).then(setUser).catch(logout) }, [token])
  useEffect(() => {
    if (!token || !user) return
    setLoading(true)
    Promise.all([api<Room[]>('/rooms', token), api<Booking[]>('/bookings', token)])
      .then(([available, owned]) => { setRooms(available); setBookings(owned) })
      .catch((cause: ApiError) => actionFeedback.fromApi(cause))
      .finally(() => setLoading(false))
  }, [token, user, page])
  useEffect(() => {
    if (page === 'admin' && token && user?.role === 'ADMIN') {
      api<Room[]>('/rooms?include_inactive=true', token).then(setRooms).catch((cause: ApiError) => actionFeedback.fromApi(cause))
    }
  }, [page, token, user])

  function navigate(destination: Page) {
    setPage(destination)
    bookingFeedback.clear(); roomFeedback.clear(); actionFeedback.clear()
  }

  async function authenticate(event: React.FormEvent) {
    event.preventDefault()
    if (!authFeedback.validate(validateEmailPassword(email, password, authMode))) return
    setBusy(true)
    try {
      if (authMode === 'register') await api<User>('/auth/register', null, 'POST', { email: email.trim(), password })
      const result = await api<{ access_token: string }>('/auth/login', null, 'POST', { email: email.trim(), password })
      localStorage.setItem('bookinglab_token', result.access_token)
      setToken(result.access_token)
      setPassword('')
      authFeedback.clear()
    } catch (cause) { authFeedback.fromApi(cause) }
    finally { setBusy(false) }
  }

  async function createBooking(event: React.FormEvent) {
    event.preventDefault()
    if (!selected || !token) return
    if (!bookingFeedback.validate(validateBooking(title, date, start, duration, attendees, selected.capacity))) return
    setBusy(true)
    try {
      await api<Booking>('/bookings', token, 'POST', {
        room_id: selected.id, title: title.trim(), booking_date: date,
        start_time: start, duration_minutes: duration, attendees: Number(attendees)
      })
      setTitle('')
      bookingFeedback.clear()
      navigate('bookings')
    } catch (cause) { bookingFeedback.fromApi(cause) }
    finally { setBusy(false) }
  }

  async function refreshBookings() {
    if (token) setBookings(await api<Booking[]>('/bookings', token))
  }

  async function bookingAction(booking: Booking, kind: 'pay' | 'cancel') {
    if (!token) return
    actionFeedback.clear(); setPaymentMessage(''); setBusy(true)
    try {
      await api<Booking>(`/bookings/${booking.id}/${kind}`, token, 'POST')
      await refreshBookings()
      if (kind === 'pay') {
        let finished = false
        for (let count = 0; count < 10; count++) {
          await new Promise(resolve => setTimeout(resolve, 1000))
          const latest = await api<Booking>(`/bookings/${booking.id}`, token)
          setBookings(previous => previous.map(item => item.id === latest.id ? latest : item))
          if (latest.status !== 'PAYMENT_PENDING') { finished = true; break }
        }
        if (!finished) setPaymentMessage('Оплата обрабатывается')
      }
    } catch (cause) { actionFeedback.fromApi(cause) }
    finally { setBusy(false) }
  }

  async function createRoom(event: React.FormEvent) {
    event.preventDefault()
    if (!token) return
    if (!roomFeedback.validate(validateRoom(roomName, roomCapacity, roomPrice))) return
    setBusy(true)
    try {
      await api<Room>('/rooms', token, 'POST', { name: roomName.trim(), capacity: Number(roomCapacity), price_per_30min_kopeks: Number(roomPrice) })
      setRoomName('')
      roomFeedback.clear()
      setRooms(await api<Room[]>('/rooms?include_inactive=true', token))
    } catch (cause) { roomFeedback.fromApi(cause) }
    finally { setBusy(false) }
  }

  async function updateRoom(room: Room, patch: Partial<Room>) {
    if (!token) return
    await api<Room>(`/rooms/${room.id}`, token, 'PATCH', patch)
    setRooms(await api<Room[]>('/rooms?include_inactive=true', token))
  }

  return <main className="shell">
    <header>
      <h1>BookingLab</h1><span>Переговорные комнаты</span>
      {user && <div className="account"><span data-testid="current-user">{user.email}</span><button data-testid="logout-button" type="button" onClick={logout}>Выйти</button></div>}
    </header>

    {!user ? <section className="panel auth" data-testid="auth-screen">
      <h2>{authMode === 'login' ? 'Вход' : 'Регистрация'}</h2>
      <form noValidate data-testid="auth-form" onSubmit={authenticate}>
        <label>Email
          <input data-testid="auth-email" type="email" value={email} aria-invalid={Boolean(authFeedback.fields.email)} aria-describedby={authFeedback.fields.email ? 'auth-email-error' : undefined} onChange={event => { setEmail(event.target.value); authFeedback.clearField('email') }} />
          <FieldError id="auth-email-error" testId="auth-email-error" message={authFeedback.fields.email} />
        </label>
        <label>Пароль
          <input data-testid="auth-password" type="password" value={password} aria-invalid={Boolean(authFeedback.fields.password)} aria-describedby={authFeedback.fields.password ? 'auth-password-error' : undefined} onChange={event => { setPassword(event.target.value); authFeedback.clearField('password') }} />
          <FieldError id="auth-password-error" testId="auth-password-error" message={authFeedback.fields.password} />
        </label>
        <button data-testid={authMode === 'login' ? 'login-submit' : 'register-submit'} type="submit" disabled={busy}>{busy ? 'Подождите…' : authMode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button>
        <FormError message={authFeedback.message} />
      </form>
      <button data-testid="auth-mode-toggle" className="link" type="button" onClick={() => { authFeedback.clear(); setAuthMode(authMode === 'login' ? 'register' : 'login') }}>{authMode === 'login' ? 'Создать аккаунт' : 'Уже есть аккаунт'}</button>
    </section> : <>
      <nav aria-label="Разделы">
        <button data-testid="nav-rooms" className={page === 'rooms' ? 'active' : ''} onClick={() => navigate('rooms')}>Комнаты</button>
        <button data-testid="nav-bookings" className={page === 'bookings' ? 'active' : ''} onClick={() => navigate('bookings')}>Мои брони</button>
        {user.role === 'ADMIN' && <button data-testid="nav-admin" className={page === 'admin' ? 'active' : ''} onClick={() => navigate('admin')}>Управление комнатами</button>}
      </nav>
      {loading && <p data-testid="page-loading" role="status">Загрузка…</p>}

      {page === 'rooms' && <section data-testid="rooms-screen">
        <h2>Доступные комнаты</h2>
        <div className="grid" data-testid="rooms-list">{rooms.filter(room => room.is_active).map(room =>
          <article className="panel" data-testid={`room-card-${room.id}`} key={room.id}>
            <h3 data-testid="room-name">{room.name}</h3>
            <p data-testid="room-capacity">До {room.capacity} человек</p>
            <p data-testid="room-price">{money(room.price_per_30min_kopeks)} / 30 минут</p>
            <button data-testid="room-book-button" onClick={() => { setSelected(room); bookingFeedback.clear(); navigate('book') }}>Забронировать</button>
          </article>
        )}</div>
      </section>}

      {page === 'book' && selected && <section className="panel" data-testid="booking-screen">
        <h2>Бронирование: {selected.name}</h2>
        <p>{money(selected.price_per_30min_kopeks)} / 30 минут · до {selected.capacity} человек</p>
        <form noValidate data-testid="booking-form" onSubmit={createBooking}>
          <label>Название встречи
            <input data-testid="booking-title" value={title} aria-invalid={Boolean(bookingFeedback.fields.title)} aria-describedby={bookingFeedback.fields.title ? 'booking-title-error' : undefined} onChange={event => { setTitle(event.target.value); bookingFeedback.clearField('title') }} />
            <FieldError id="booking-title-error" testId="booking-title-error" message={bookingFeedback.fields.title} />
          </label>
          <label>Дата
            <input data-testid="booking-date" type="date" value={date} aria-invalid={Boolean(bookingFeedback.fields.booking_date)} aria-describedby={bookingFeedback.fields.booking_date ? 'booking-date-error' : undefined} onChange={event => { setDate(event.target.value); bookingFeedback.clearField('booking_date') }} />
            <FieldError id="booking-date-error" testId="booking-date-error" message={bookingFeedback.fields.booking_date} />
          </label>
          <label>Начало
            <input data-testid="booking-start-time" type="time" step="1800" value={start} aria-invalid={Boolean(bookingFeedback.fields.start_time)} aria-describedby={bookingFeedback.fields.start_time ? 'booking-start-time-error' : undefined} onChange={event => { setStart(event.target.value); bookingFeedback.clearField('start_time') }} />
            <FieldError id="booking-start-time-error" testId="booking-start-time-error" message={bookingFeedback.fields.start_time} />
          </label>
          <label>Длительность
            <select data-testid="booking-duration" value={duration} aria-invalid={Boolean(bookingFeedback.fields.duration_minutes)} aria-describedby={bookingFeedback.fields.duration_minutes ? 'booking-duration-error' : undefined} onChange={event => { setDuration(Number(event.target.value)); bookingFeedback.clearField('duration_minutes') }}>{[30, 60, 90, 120].map(value => <option key={value} value={value}>{value} минут</option>)}</select>
            <FieldError id="booking-duration-error" testId="booking-duration-error" message={bookingFeedback.fields.duration_minutes} />
          </label>
          <label>Участники
            <input data-testid="booking-attendees" type="number" value={attendees} aria-invalid={Boolean(bookingFeedback.fields.attendees)} aria-describedby={bookingFeedback.fields.attendees ? 'booking-attendees-error' : undefined} onChange={event => { setAttendees(event.target.value); bookingFeedback.clearField('attendees') }} />
            <FieldError id="booking-attendees-error" testId="booking-attendees-error" message={bookingFeedback.fields.attendees} />
          </label>
          <p data-testid="booking-total-price">Итого: {money(selected.price_per_30min_kopeks * duration / 30)}</p>
          <button data-testid="booking-submit" type="submit" disabled={busy}>Создать бронь</button>
          <FormError message={bookingFeedback.message} />
        </form>
      </section>}

      {page === 'bookings' && <section data-testid="bookings-screen">
        <h2>Мои брони</h2>
        {bookings.length === 0 && <p data-testid="bookings-empty">Броней пока нет</p>}
        <div className="stack" data-testid="bookings-list">{bookings.map(booking =>
          <article className="panel" data-testid={`booking-card-${booking.id}`} key={booking.id}>
            <h3 data-testid="booking-card-title">{booking.title}</h3>
            <p>{booking.booking_date} · {booking.start_time.slice(0, 5)}–{booking.end_time.slice(0, 5)}</p>
            <p data-testid="booking-card-price">{money(booking.total_price_kopeks)} · участников: {booking.attendees}</p>
            <p data-testid="booking-status" role="status">{statusLabels[booking.status] || booking.status}</p>
            <p>Оплатить до: {new Date(booking.expires_at).toLocaleString('ru-RU')}</p>
            {booking.status === 'CREATED' && <button data-testid="pay-button" disabled={busy} onClick={() => bookingAction(booking, 'pay')}>Оплатить</button>}
            {['CREATED', 'PAYMENT_PENDING'].includes(booking.status) && <button data-testid="cancel-button" disabled={busy} onClick={() => bookingAction(booking, 'cancel')}>Отменить</button>}
          </article>
        )}</div>
        {paymentMessage && <p data-testid="payment-message" role="status">{paymentMessage}</p>}
      </section>}

      {page === 'admin' && user.role === 'ADMIN' && <section data-testid="admin-screen">
        <h2>Управление комнатами</h2>
        <form noValidate className="panel" data-testid="room-create-form" onSubmit={createRoom}>
          <h3>Добавить комнату</h3>
          <label>Название
            <input data-testid="room-create-name" value={roomName} aria-invalid={Boolean(roomFeedback.fields.name)} aria-describedby={roomFeedback.fields.name ? 'room-create-name-error' : undefined} onChange={event => { setRoomName(event.target.value); roomFeedback.clearField('name') }} />
            <FieldError id="room-create-name-error" testId="room-create-name-error" message={roomFeedback.fields.name} />
          </label>
          <label>Вместимость
            <input data-testid="room-create-capacity" type="number" value={roomCapacity} aria-invalid={Boolean(roomFeedback.fields.capacity)} aria-describedby={roomFeedback.fields.capacity ? 'room-create-capacity-error' : undefined} onChange={event => { setRoomCapacity(event.target.value); roomFeedback.clearField('capacity') }} />
            <FieldError id="room-create-capacity-error" testId="room-create-capacity-error" message={roomFeedback.fields.capacity} />
          </label>
          <label>Цена за 30 минут, копейки
            <input data-testid="room-create-price" type="number" value={roomPrice} aria-invalid={Boolean(roomFeedback.fields.price_per_30min_kopeks)} aria-describedby={roomFeedback.fields.price_per_30min_kopeks ? 'room-create-price-error' : undefined} onChange={event => { setRoomPrice(event.target.value); roomFeedback.clearField('price_per_30min_kopeks') }} />
            <FieldError id="room-create-price-error" testId="room-create-price-error" message={roomFeedback.fields.price_per_30min_kopeks} />
          </label>
          <button data-testid="room-create-submit" type="submit" disabled={busy}>Добавить</button>
          <FormError message={roomFeedback.message} />
        </form>
        <div className="stack" data-testid="admin-rooms-list">{rooms.map(room => <RoomEditor key={room.id} room={room} onSave={patch => updateRoom(room, patch)} />)}</div>
      </section>}
      <FormError message={actionFeedback.message} />
    </>}
  </main>
}

createRoot(document.getElementById('root')!).render(<App />)
