import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login({ home }) {
  const { login } = useAuth()
  const nav = useNavigate()
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    try {
      const d = await login(u, p)
      nav(home[d.role])
    } catch {
      setErr('Wrong username or password')
    }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-xl border border-slate-200 bg-white p-6">
      <h1 className="text-2xl font-bold text-teal-800">SlideSense</h1>
      <p className="mb-4 text-sm text-slate-600">Research and decision-support tool. Not for clinical use.</p>
      <form onSubmit={submit} className="space-y-3">
        <input className="w-full rounded border p-2" placeholder="Username" value={u} onChange={(e) => setU(e.target.value)} />
        <input className="w-full rounded border p-2" type="password" placeholder="Password" value={p} onChange={(e) => setP(e.target.value)} />
        {err && <p className="text-sm text-red-700">{err}</p>}
        <button className="w-full rounded bg-teal-800 p-2 font-semibold text-white">Sign in</button>
      </form>
    </div>
  )
}