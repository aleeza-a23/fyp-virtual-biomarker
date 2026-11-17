import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../auth'

export default function ResearcherHome() {
  const [rows, setRows] = useState([])
  const { logout } = useAuth()
  const nav = useNavigate()
  useEffect(() => { api.get('/research/cohort').then((r) => setRows(r.data)) }, [])
  const exportCsv = () => {
    const csv = ['coded_id,cancer,biomarker,score,is_demo', ...rows.map((r) => `${r.coded_id},${r.cancer},${r.biomarker},${r.score},${r.is_demo}`)].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = 'cohort_deidentified.csv'
    a.click()
  }
  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="text-2xl font-bold">Researcher portal</h1>
      <p className="mb-3 text-sm text-slate-600">De-identified data from consenting patients only. No names, no slide images.</p>
      <table className="w-full border bg-white text-sm">
        <thead><tr className="bg-slate-50 text-left"><th className="p-2">Coded ID</th><th>Cancer</th><th>Biomarker</th><th>Score</th><th>Source</th></tr></thead>
        <tbody>{rows.map((r, i) => (<tr key={i} className="border-t"><td className="p-2">{r.coded_id}</td><td>{r.cancer}</td><td>{r.biomarker}</td><td>{r.score}</td><td>{r.is_demo ? 'Demo output' : 'Trained model'}</td></tr>))}</tbody>
      </table>
      <button className="mt-3 rounded bg-teal-800 px-3 py-1 font-semibold text-white" onClick={exportCsv}>Export de-identified CSV</button>
      <button className="ml-4 text-teal-800 underline" onClick={() => { logout(); nav('/login') }}>Sign out</button>
    </div>
  )
}