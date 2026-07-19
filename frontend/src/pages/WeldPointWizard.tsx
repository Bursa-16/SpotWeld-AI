import { FormEvent, useEffect, useState } from 'react'
import { createWeldPoint, listWeldPoints } from '../api/client'
import type { Project, WeldPoint } from '../types/project'
import type { WeldAnalysisRequest } from '../types/weld'

const baseInput: WeldAnalysisRequest = {
  material_family:'Düşük / Orta Karbonlu Çelik', material_subtype:'Düşük karbonlu çelik', stack_count:'2T',
  layers:[
    {material_family:'Düşük / Orta Karbonlu Çelik',material_subtype:'Düşük karbonlu çelik',thickness_mm:1,coated:false},
    {material_family:'Düşük / Orta Karbonlu Çelik',material_subtype:'Düşük karbonlu çelik',thickness_mm:1,coated:false}
  ],
  current_ka:8,weld_cycles:12,force_kn:3,tip_diameter_mm:6,squeeze_cycles:15,hold_cycles:15,
  cooling_flow_lpm:6,cooling_temp_c:20,dc_current:true,adhesive:false,shunt_risk:false
}

export function WeldPointWizard({ project, onBack }: { project: Project; onBack:()=>void }) {
  const [points,setPoints]=useState<WeldPoint[]>([]); const [pointCode,setPointCode]=useState('W001')
  const [partNo,setPartNo]=useState(''); const [input,setInput]=useState(baseInput); const [message,setMessage]=useState('')
  async function refresh(){setPoints(await listWeldPoints(project.id))}
  useEffect(()=>{refresh().catch(e=>setMessage(String(e)))},[project.id])
  async function submit(e:FormEvent){e.preventDefault(); try{
    const created=await createWeldPoint(project.id,{point_code:pointCode,part_no:partNo,criticality:'Standart',analysis_input:input})
    setMessage(`Kaydedildi: ${created.point_code} — skor %${created.analysis_result.score.toFixed(0)}`); await refresh()
  }catch(err){setMessage(err instanceof Error?err.message:'Kayıt başarısız')}}
  return <main className="page"><header><button className="secondary" onClick={onBack}>← Projeler</button><h1>{project.project_code} — {project.project_name}</h1></header>
    <section className="grid"><form className="panel" onSubmit={submit}><h2>Kaynak Noktası Sihirbazı</h2>
      <label>Nokta ID<input value={pointCode} onChange={e=>setPointCode(e.target.value)} /></label>
      <label>Parça no<input value={partNo} onChange={e=>setPartNo(e.target.value)} /></label>
      <label>Akım (kA)<input type="number" value={input.current_ka} onChange={e=>setInput({...input,current_ka:Number(e.target.value)})}/></label>
      <label>Kaynak süresi<input type="number" value={input.weld_cycles} onChange={e=>setInput({...input,weld_cycles:Number(e.target.value)})}/></label>
      <label>Kuvvet (kN)<input type="number" value={input.force_kn} onChange={e=>setInput({...input,force_kn:Number(e.target.value)})}/></label>
      <button>Analiz Et ve Kaydet</button>{message&&<p>{message}</p>}</form>
      <div className="panel"><h2>Kayıtlı Kaynak Noktaları</h2><table><thead><tr><th>ID</th><th>Parça</th><th>Skor</th><th>Risk</th><th>Rev.</th></tr></thead><tbody>
        {points.map(p=><tr key={p.id}><td>{p.point_code}</td><td>{p.part_no}</td><td>%{p.analysis_result.score.toFixed(0)}</td><td>{p.analysis_result.risk_level}</td><td>{p.version_no}</td></tr>)}
      </tbody></table></div></section></main>
}
