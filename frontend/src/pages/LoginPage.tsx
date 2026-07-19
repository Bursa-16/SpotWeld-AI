
import { useState } from 'react'
import { login } from '../api/client'

type Props = { onLogin: () => void }

export function LoginPage({ onLogin }: Props) {
  const [email, setEmail] = useState('admin@spotwelding.example')
  const [password, setPassword] = useState('ChangeMe123!')
  const [error, setError] = useState('')

  async function submit() {
    try {
      setError('')
      await login(email, password)
      onLogin()
    } catch {
      setError('Giriş başarısız. E-posta veya şifreyi kontrol edin.')
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <h1>Spot Welding Platform</h1>
        <p>Kurumsal giriş</p>
        <label>E-posta<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Şifre<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <button onClick={submit}>Giriş Yap</button>
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  )
}
