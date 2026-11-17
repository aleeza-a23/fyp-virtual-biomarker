import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api'
import SlideViewer from '../components/SlideViewer'

export default function CaseDetail() {
  const { id } = useParams()
  const [c, setC] = useState(null)
  const [slides, setSlides] = useState([])
  const [decision, setDecision] = useState('')
  const [comment, setComment] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState('')

  const load = () => {
    api.get(`/cases/${id}`).then((r) => setC(r.data))
    api.get(`/cases/${id}/slides`).then((r) => setSlides(r.data))
  }
  useEffect(load, [id])

  const upload = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    try { await api.post(`/cases/${id}/slides`, fd); setMsg('Slide uploaded'); load() }
    catch (err) { setMsg(err.response?.data?.detail || 'Upload failed') }
  }
  const analyze = async () => { await api.post(`/cases/${id}/analyze`); load() }
  const sign = async () => {
    try { await api.post(`/cases/${id}/signoff`, { decision, comment, next_step: next }); setMsg('Signed off'); load() }
    catch (err) { setMsg(err.response?.data?.detail || 'Sign-off failed') }
  }
  const pdf = async () => {
    const r = await api.get(`/cases/${id}/report`, { responseType: 'blob' })
    window.open(URL.createObjectURL(r.data))
  }

  if (!c) return <div className="p-6">Loading...</div>
  return (
    <div className="mx-auto max-w-6xl p-6">
      <Link to="/doctor" className="text-sm text-teal-800 underline">Back to cases</Link>
      <h1 className="text-2xl font-bold">{c.code} <span className="text-base font-normal text-slate-600">{c.cancer}, patient {c.patient}, {c.status}</span></h1>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <div className="md:col-span-2">
          {slides.length ? <SlideViewer slideId={slides[0].id} /> : <p className="rounded border bg-white p-6">No slide yet. Upload an .svs file.</p>}
          <input type="file" accept=".svs,.tif,.tiff" onChange={upload} className="mt-3" />
          <p className="mt-1 text-sm text-slate-600">Heatmap overlay arrives once a real model is connected.</p>
        </div>
        <div className="space-y-4">
          <div className="rounded border bg-white p-4">
            <h2 className="mb-2 font-semibold">Predictions</h2>
            {c.predictions.map((p) => (
              <div key={p.biomarker} className="flex justify-between border-b py-1 text-sm">
                <span>{p.biomarker} <span className="text-slate-500">({p.gene})</span></span>
                <span>{p.level} {p.score.toFixed(2)} {p.is_demo && <b className="ml-1 rounded bg-amber-100 px-1 text-amber-900">Demo</b>}</span>
              </div>
            ))}
            <button onClick={analyze} className="mt-3 rounded border border-teal-800 px-3 py-1 text-teal-800">Run demo analysis</button>
            <p className="mt-2 text-xs text-slate-500">Model: {c.predictions[0]?.model_name || 'none'}. Validation: not validated.</p>
          </div>
          <div className="rounded border bg-white p-4">
            <h2 className="mb-2 font-semibold">Pathologist review</h2>
            <select className="mb-2 w-full rounded border p-1" value={decision} onChange={(e) => setDecision(e.target.value)}>
              <option value="">Choose a decision</option><option>Agree</option><option>Modify</option><option>Reject</option>
            </select>
            <textarea className="mb-2 w-full rounded border p-1" rows="2" placeholder="Comment (required if Modify or Reject)" value={comment} onChange={(e) => setComment(e.target.value)} />
            <input className="mb-2 w-full rounded border p-1" placeholder="Next step shown to the patient" value={next} onChange={(e) => setNext(e.target.value)} />
            <button onClick={sign} className="rounded bg-teal-800 px-3 py-1 font-semibold text-white">Sign off</button>
            <button onClick={pdf} className="ml-2 rounded border border-teal-800 px-3 py-1 text-teal-800">PDF report</button>
            {msg && <p className="mt-2 text-sm">{msg}</p>}
          </div>
        </div>
      </div>
      <p className="mt-6 rounded border-l-4 border-amber-600 bg-amber-50 p-3 text-sm text-amber-900">
        Research and decision-support tool only. Scores are predicted from H&amp;E images using RNA-derived proxy labels, not direct protein measurements. Not validated for clinical use.
      </p>
    </div>
  )
}