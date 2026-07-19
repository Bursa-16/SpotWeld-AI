import { FormEvent, useEffect, useState } from 'react'
import { createProject, listProjects } from '../api/client'
import type { Project } from '../types/project'

export function ProjectsPage({ onOpen }: { onOpen: (project: Project) => void }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [customer, setCustomer] = useState('')
  const [platform, setPlatform] = useState('')
  const [error, setError] = useState('')

  async function refresh() { setProjects(await listProjects()) }
  useEffect(() => { refresh().catch(e => setError(String(e))) }, [])

  async function submit(e: FormEvent) {
    e.preventDefault(); setError('')
    try {
      await createProject({ project_code: code, project_name: name, customer, vehicle_platform: platform })
      setCode(''); setName(''); setCustomer(''); setPlatform(''); await refresh()
    } catch (err) { setError(err instanceof Error ? err.message : 'Kayıt başarısız') }
  }

  return <main className="page">
    <header><h1>Projeler</h1><p>Proje ve kaynak noktası yönetimi</p></header>
    <section className="grid">
      <form className="panel" onSubmit={submit}>
        <h2>Yeni Proje</h2>
        <label>Proje kodu<input value={code} onChange={e=>setCode(e.target.value)} required /></label>
        <label>Proje adı<input value={name} onChange={e=>setName(e.target.value)} required /></label>
        <label>Müşteri<input value={customer} onChange={e=>setCustomer(e.target.value)} /></label>
        <label>Araç / platform<input value={platform} onChange={e=>setPlatform(e.target.value)} /></label>
        <button>Projeyi Kaydet</button>{error && <p className="error">{error}</p>}
      </form>
      <div className="panel"><h2>Proje Listesi</h2>
        <div className="cards">{projects.map(p=><article className="project-card" key={p.id} onClick={()=>onOpen(p)}>
          <strong>{p.project_code}</strong><h3>{p.project_name}</h3><p>{p.customer || 'Müşteri belirtilmedi'}</p><span>{p.status}</span>
        </article>)}</div>
      </div>
    </section>
  </main>
}
