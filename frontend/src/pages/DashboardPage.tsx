
import { useEffect, useState } from 'react'
import { currentUser, dashboard } from '../api/client'

type DashboardData = {
  total_projects: number
  active_projects: number
  total_weld_points: number
  risky_weld_points: number
  pending_approvals: number
  rejected_approvals: number
  total_users: number
  recent_audit_events: number
}

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [user, setUser] = useState<{ full_name: string; role: string } | null>(null)

  useEffect(() => {
    Promise.all([dashboard(), currentUser()]).then(([d, u]) => {
      setData(d)
      setUser(u)
    })
  }, [])

  const cards = data ? [
    ['Toplam Proje', data.total_projects],
    ['Aktif Proje', data.active_projects],
    ['Toplam Weld Point', data.total_weld_points],
    ['Riskli Nokta', data.risky_weld_points],
    ['Bekleyen Onay', data.pending_approvals],
    ['Reddedilen Onay', data.rejected_approvals],
    ['Kullanıcı', data.total_users],
    ['Son 7 Gün Audit', data.recent_audit_events],
  ] : []

  return (
    <main className="page">
      <header className="topbar">
        <div><h1>Dashboard</h1><p>{user ? `${user.full_name} — ${user.role}` : 'Yükleniyor...'}</p></div>
        <button className="logout" onClick={() => {
          localStorage.clear()
          window.location.reload()
        }}>Çıkış</button>
      </header>
      <section className="dashboard-grid">
        {cards.map(([label, value]) => (
          <article className="dashboard-card" key={String(label)}>
            <span>{label}</span><strong>{value}</strong>
          </article>
        ))}
      </section>
    </main>
  )
}
