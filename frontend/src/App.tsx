import { useState } from 'react'
import { DashboardPage } from './pages/DashboardPage'
import { EngineeringPage } from './pages/EngineeringPage'
import { LoginPage } from './pages/LoginPage'
import { OptimizationPage } from './pages/OptimizationPage'
import { FailureProbabilityPage } from './pages/FailureProbabilityPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { WeldPointWizard } from './pages/WeldPointWizard'
import type { Project } from './types/project'
import './styles.css'

type Page='dashboard'|'projects'|'engineering'|'optimization'|'failure'
export default function App(){
 const [authenticated,setAuthenticated]=useState(Boolean(localStorage.getItem('access_token')))
 const [page,setPage]=useState<Page>('dashboard'); const [project,setProject]=useState<Project|null>(null)
 if(!authenticated) return <LoginPage onLogin={()=>setAuthenticated(true)}/>
 if(project) return <WeldPointWizard project={project} onBack={()=>setProject(null)}/>
 return <><nav className="main-nav"><button onClick={()=>setPage('dashboard')}>Dashboard</button><button onClick={()=>setPage('projects')}>Projects</button><button onClick={()=>setPage('engineering')}>Engineering Lab</button><button onClick={()=>setPage('optimization')}>Optimization Lab</button><button onClick={()=>setPage('failure')}>Failure Analysis</button></nav>{page==='dashboard'?<DashboardPage/>:page==='projects'?<ProjectsPage onOpen={setProject}/>:page==='engineering'?<EngineeringPage/>:page==='optimization'?<OptimizationPage/>:<FailureProbabilityPage/>}</>
}
