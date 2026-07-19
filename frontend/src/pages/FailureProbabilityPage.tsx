
import { useState } from 'react'
import client from '../api/client'

type FailureMode = {
  code: string
  title: string
  probability_percent: number
  confidence: string
  severity: string
  contributions: Array<{
    factor: string
    normalized_effect: number
    explanation: string
  }>
  validation_tests: string[]
  recommended_actions: string[]
}

type AnalysisResult = {
  failure_modes: FailureMode[]
  priority_actions: string[]
  disclaimer: string
}

export function FailureProbabilityPage() {
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(false)

  async function analyze() {
    setLoading(true)
    try {
      const response = await client.post('/failure-probability/analyze', {
        material_family: 'Galvanizli / Kaplamalı Çelik',
        stack_count: '2T',
        coated: true,
        adhesive: false,
        shunt_risk: false,
        thicknesses_mm: [1.0, 1.0],

        current_ka: 11.5,
        weld_cycles: 15,
        force_kn: 2.2,
        tip_diameter_mm: 6.0,
        squeeze_cycles: 15,
        hold_cycles: 12,
        cooling_flow_lpm: 5.0,
        cooling_temp_c: 28,

        recommended_current_min_ka: 8.0,
        recommended_current_max_ka: 10.5,
        recommended_time_min_cycles: 10,
        recommended_time_max_cycles: 12,
        recommended_force_min_kn: 2.5,
        recommended_force_max_kn: 3.5,
        recommended_tip_min_mm: 6,
        recommended_tip_max_mm: 6,

        predicted_nugget_mm: 5.0,
        minimum_nugget_mm: 4.2,
      })
      setResult(response.data)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="page">
      <header>
        <h1>Potential Failure Analysis</h1>
        <p>Seçilen kaynak parametrelerinden potansiyel hata olasılıkları</p>
      </header>

      <section className="panel">
        <button onClick={analyze} disabled={loading}>
          {loading ? 'Hesaplanıyor...' : 'Hata Olasılıklarını Hesapla'}
        </button>

        {result && (
          <>
            <h2>Öncelikli riskler</h2>
            <div className="failure-grid">
              {result.failure_modes.slice(0, 6).map((mode) => (
                <article className="failure-card" key={mode.code}>
                  <div className="failure-head">
                    <h3>{mode.title}</h3>
                    <strong>%{mode.probability_percent.toFixed(1)}</strong>
                  </div>
                  <p>{mode.severity} · Güven: {mode.confidence}</p>
                  <div className="risk-bar">
                    <span style={{ width: `${mode.probability_percent}%` }} />
                  </div>

                  <h4>Ana etkiler</h4>
                  <ul>
                    {mode.contributions.slice(0, 3).map((item) => (
                      <li key={item.factor}>
                        <strong>{item.factor}:</strong> {item.explanation}
                      </li>
                    ))}
                  </ul>

                  <h4>Önerilen aksiyon</h4>
                  <ol>
                    {mode.recommended_actions.slice(0, 2).map((action) => (
                      <li key={action}>{action}</li>
                    ))}
                  </ol>
                </article>
              ))}
            </div>

            <h2>Genel öncelikli aksiyonlar</h2>
            <ol>
              {result.priority_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ol>

            <p className="notice">{result.disclaimer}</p>
          </>
        )}
      </section>
    </main>
  )
}
