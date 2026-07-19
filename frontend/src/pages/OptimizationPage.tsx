import { useState } from 'react'
import client from '../api/client'
export function OptimizationPage(){
 const [result,setResult]=useState<any>(null); const [model4,setModel4]=useState<any>(null)
 async function optimize(){const r=await client.post('/optimization/doe',{material_family:'Düşük / Orta Karbonlu Çelik',thickness_mm:1,min_nugget_mm:4.2,target_nugget_mm:5.2,current_min_ka:6,current_max_ka:12,current_step_ka:.5,time_min_cycles:8,time_max_cycles:18,time_step_cycles:1,force_min_kn:2,force_max_kn:4,force_step_kn:.5});setResult(r.data)}
 async function runModel4(){const r=await client.post('/optimization/model4/predict',{Current:8000,Force:300,Time:12,Cooling:0,Sequence:15,Holding:15,SheetThick:1});setModel4(r.data)}
 return <main className="page"><header><h1>Optimization Lab</h1><p>DOE arama ve Model-4 açıklaması</p></header><section className="grid"><article className="panel"><h2>DOE</h2><button onClick={optimize}>Optimum Parametreyi Bul</button>{result&&<><p>Kombinasyon: <strong>{result.evaluated_count}</strong></p><pre>{JSON.stringify(result.best,null,2)}</pre></>}</article><article className="panel"><h2>Model-4</h2><button onClick={runModel4}>Tahmin Et</button>{model4&&<><p>Tahmin: <strong>{Number(model4.prediction_mm).toFixed(3)} mm</strong></p><table><thead><tr><th>Terim</th><th>Katkı</th></tr></thead><tbody>{model4.top_contributions.map((r:any)=><tr key={r.term}><td>{r.term}</td><td>{Number(r.contribution).toFixed(3)}</td></tr>)}</tbody></table></>}</article></section></main>
}
