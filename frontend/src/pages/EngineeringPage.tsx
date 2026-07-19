
import { useState } from 'react'
import client from '../api/client'

type LobePoint = {
  current_ka: number
  weld_cycles: number
  nugget_mm: number
  expulsion_risk: number
  fusion_risk: number
  zone: string
}

export function EngineeringPage() {
  const [result, setResult] = useState<{
    optimum: LobePoint | null
    safe_count: number
    warning_count: number
    unsafe_count: number
    sensitivity: Array<Record<string, unknown>>
  } | null>(null)

  async function calculate() {
    const response = await client.post('/engineering/weld-lobe', {
      material_family: 'Düşük / Orta Karbonlu Çelik',
      thickness_mm: 1.0,
      force_kn: 3.0,
      min_nugget_mm: 4.2,
      current_min_ka: 6.0,
      current_max_ka: 12.0,
      current_step_ka: 0.5,
      time_min_cycles: 8,
      time_max_cycles: 18,
      time_step_cycles: 1,
    })
    setResult(response.data)
  }

  return (
    <main className="page">
      <header>
        <h1>Engineering Lab</h1>
        <p>Weld lobe, hassasiyet ve optimum nokta analizi</p>
      </header>

      <section className="panel">
        <button onClick={calculate}>Weld Lobe Hesapla</button>

        {result && (
          <>
            <div className="dashboard-grid engineering-metrics">
              <article className="dashboard-card">
                <span>Güvenli Nokta</span><strong>{result.safe_count}</strong>
              </article>
              <article className="dashboard-card">
                <span>Uyarı Noktası</span><strong>{result.warning_count}</strong>
              </article>
              <article className="dashboard-card">
                <span>Uygun Olmayan</span><strong>{result.unsafe_count}</strong>
              </article>
              <article className="dashboard-card">
                <span>Optimum</span>
                <strong>{result.optimum ? `${result.optimum.current_ka} kA / ${result.optimum.weld_cycles} cyc` : '-'}</strong>
              </article>
            </div>

            <h2>Parametre Hassasiyeti</h2>
            <table>
              <thead><tr><th>Sıra</th><th>Parametre</th><th>Etki</th><th>Duyarlılık</th></tr></thead>
              <tbody>
                {result.sensitivity.map((row) => (
                  <tr key={String(row.parameter)}>
                    <td>{String(row.priority_rank)}</td>
                    <td>{String(row.parameter)}</td>
                    <td>{String(row.absolute_impact)}</td>
                    <td>{String(row.sensitivity_mm_per_unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </main>
  )
}
