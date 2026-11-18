import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../auth'

const fmt = (d) => (d ? new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : 'Not yet')
const Level = ({ p }) =>
  p ? (
    <span className={`rounded-full px-2 text-sm font-semibold ${p.level === 'High' ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'}`}>
      {p.level}
    </span>
  ) : <span className="text-slate-400">-</span>

export default function DoctorDashboard() {
  const [patients, setPatients] = useState([])
  const [cases, setCases] = useState([])
  const { user, logout } = useAuth()
  const nav = useNavigate()

  useEffect(() => {
    api.get('/patients').then((r) => setPatients(r.data))
    api.get('/cases').then((r) => setCases(r.data))
  }, [])

  const by = (c, b) => c.predictions.find((x) => x.biomarker === b)

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-2 rounded bg-amber-100 p-2 text-center text-sm text-amber-900">
        Research prototype, not for clinical use. Scores marked Demo are not model predictions.
      </div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Patients and cases</h1>
        <div className="text-sm">{user.name} <button className="ml-3 text-teal-800 underline" onClick={() => { logout(); nav('/login') }}>Sign out</button></div>
      </div>

      <h2 className="mb-2 font-semibold">Patients</h2>
      <table className="mb-6 w-full border bg-white text-sm">
        <thead><tr className="bg-slate-50 text-left"><th className="p-2">Code</th><th>Registered</th><th>Age</th><th>Gender</th><th>Cases</th><th>Last analysis</th></tr></thead>
        <tbody>{patients.map((p) => (
          <tr key={p.code} className="border-t"><td className="p-2 font-semibold">{p.code}</td><td>{fmt(p.registered_at)}</td><td>{p.age}</td><td>{p.sex}</td><td>{p.cases}</td><td>{fmt(p.last_analysis)}</td></tr>
        ))}</tbody>
      </table>

      <h2 className="mb-2 font-semibold">Cancer cases</h2>
      <table className="w-full border bg-white text-sm">
        <thead><tr className="bg-slate-50 text-left"><th className="p-2">Case</th><th>Patient</th><th>Cancer</th><th>Analysed</th><th>PD-L1</th><th>Ki-67</th><th>CD8</th><th>FOXP3</th><th>Status</th></tr></thead>
        <tbody>{cases.map((c) => (
          <tr key={c.id} className="cursor-pointer border-t hover:bg-slate-50" onClick={() => nav(`/doctor/case/${c.id}`)}>
            <td className="p-2 font-semibold">{c.code}</td><td>{c.patient}</td><td>{c.cancer}</td><td>{fmt(c.analysed_at)}</td>
            {['PD-L1', 'Ki-67', 'CD8', 'FOXP3'].map((b) => <td key={b}><Level p={by(c, b)} /></td>)}
            <td>{c.status}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="mt-2 text-xs text-slate-500">High or low is a predicted RNA-expression-based status, not an IHC result.</p>
    </div>
  )
}