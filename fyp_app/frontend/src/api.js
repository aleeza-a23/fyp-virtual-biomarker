import axios from 'axios'

export const API = 'http://127.0.0.1:8000'
const api = axios.create({ baseURL: API })

api.interceptors.request.use((c) => {
  const t = sessionStorage.getItem('token')
  if (t) c.headers.Authorization = `Bearer ${t}`
  return c
})

export default api