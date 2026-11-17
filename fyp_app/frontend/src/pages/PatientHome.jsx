import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../auth'

const names = { 'PD-L1': 'Immune checkpoint (PD-L1)', 'Ki-67': 'Cell growth (Ki-67)', CD8: 'Killer T cells (CD8)', FOXP3: 'Regulatory T cells (FOXP3)' }

export default function PatientHome() {
  const [reports, setReports] = useState([])
  const { user, logout } = useAuth()
  const nav = useNavigate()
  useEffect(() => { api.get('/me/reports').then((r) => setReports(r.data)) }, [])
  return (
    <div className="mx-auto min-h-screen max-w-sm bg-white p-5">
      <h1 className="text-xl font-bold">Hello, {user.name}</h1>
      <p className="mb-4 text-sm text-slate-600">You only see reports your doctor has reviewed.</p>
      {reports.length === 0 && <p className="text-sm">No reviewed reports yet.</p>}
      {reports.map((r) => (
        <div key={r.id} className="mb-4 rounded-lg border p-3">
          <b>{r.cancer}</b>
          <p className="text-xs text-slate-500">A research estimate. Not a diagnosis and not a treatment decision.</p>
          {r.predictions.map((p) => (
            <div key={p.biomarker} className="flex justify-between border-b py-1 text-sm"><span>{names[p.biomarker]}</span><span>Estimated level: {p.level}</span></div>
          ))}
          <p className="mt-2 text-sm"><b>Next step from your doctor:</b> {r.next_step || 'Please contact your clinic.'}</p>
          <p className="text-xs text-slate-500">Estimates need confirmation by laboratory tests.</p>
        </div>
      ))}
      <button className="text-teal-800 underline" onClick={() => { logout(); nav('/login') }}>Sign out</button>
    </div>
  )
}