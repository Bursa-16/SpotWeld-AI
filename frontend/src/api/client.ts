import axios from 'axios'
import type { WeldAnalysisRequest, WeldAnalysisResponse } from '../types/weld'
import type { Project, ProjectCreate, WeldPoint, WeldPointCreate } from '../types/project'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1',
  timeout: 15000,
})
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
export async function login(email: string, password: string) {
  const response = await client.post('/auth/login', { email, password })
  localStorage.setItem('access_token', response.data.access_token)
  localStorage.setItem('refresh_token', response.data.refresh_token)
  return response.data
}
export function logout() { localStorage.clear() }
export async function currentUser() { return (await client.get('/auth/me')).data }
export async function dashboard() { return (await client.get('/dashboard')).data }
export async function analyzeWeld(payload: WeldAnalysisRequest): Promise<WeldAnalysisResponse> {
  return (await client.post<WeldAnalysisResponse>('/weld-analysis', payload)).data
}
export async function listProjects(): Promise<Project[]> { return (await client.get<Project[]>('/projects')).data }
export async function createProject(payload: ProjectCreate): Promise<Project> { return (await client.post<Project>('/projects', payload)).data }
export async function listWeldPoints(projectId: number): Promise<WeldPoint[]> { return (await client.get<WeldPoint[]>(`/projects/${projectId}/weld-points`)).data }
export async function createWeldPoint(projectId: number, payload: WeldPointCreate): Promise<WeldPoint> {
  return (await client.post<WeldPoint>(`/projects/${projectId}/weld-points`, payload)).data
}
export default client
