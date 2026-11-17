import { createContext, useContext, useState } from 'react'
import api from './api'

const Ctx = createContext(null)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const u = sessionStorage.getItem('user')
    return u ? JSON.parse(u) : null
  })
  const login = async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    sessionStorage.setItem('token', data.token)
    sessionStorage.setItem('user', JSON.stringify(data))
    setUser(data)
    return data
  }
  const logout = () => {
    sessionStorage.clear()
    setUser(null)
  }
  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>
}