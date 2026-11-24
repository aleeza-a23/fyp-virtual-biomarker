
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api'
import { useAuth } from '../auth'

const USER_ROLES = {
  1: 'Pathologist',
  2: 'Researcher',
  3: 'Patient',
}
const displayScore = (score) => {
  const value = Number(score || 0)
  return value >= 0 && value <= 1
    ? value * 100
    : value
}
export default function ResearcherHome() {
  const [rows, setRows] = useState([])
  const [audit, setAudit] = useState([])
  const [cancerFilter, setCancerFilter] = useState('All')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const { logout } = useAuth()
  const nav = useNavigate()

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true)
        setError('')

        const [cohortResponse, auditResponse] = await Promise.all([
          api.get('/research/cohort'),
          api.get('/audit'),
        ])

        setRows(cohortResponse.data)
        setAudit(auditResponse.data)
      } catch (err) {
        setError(
          err.response?.data?.detail ||
          'Unable to load research data. Please try again.'
        )
      } finally {
        setLoading(false)
      }
    }

    loadData()
  }, [])

  const cancerTypes = useMemo(
    () => [...new Set(rows.map((r) => r.cancer).filter(Boolean))],
    [rows]
  )

  const filteredRows = useMemo(
    () => cancerFilter === 'All'
      ? rows
      : rows.filter((r) => r.cancer === cancerFilter),
    [rows, cancerFilter]
  )

  const codedCases = new Set(filteredRows.map((r) => r.coded_id)).size
  const demoCount = filteredRows.filter((r) => r.is_demo).length
  const validatedCount = filteredRows.filter((r) => !r.is_demo).length
  const biomarkerCount = new Set(filteredRows.map((r) => r.biomarker)).size

   const averageScore = filteredRows.length
  ? Math.round(
      filteredRows.reduce(
        (sum, r) => sum + displayScore(r.score),
        0
      ) / filteredRows.length
    )
   : 0
  const formatTime = (value) => {
    if (!value) return '—'
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  const exportCsv = () => {
    const escapeCsv = (value) =>
      `"${String(value ?? '').replaceAll('"', '""')}"`

    const csv = [
      ['Coded case ID', 'Cancer type', 'Biomarker', 'Illustrative score', 'Output type'],
      ...filteredRows.map((r) => [
        r.coded_id,
        r.cancer,
        r.biomarker,
        displayScore(r.score).toFixed(0),
        r.is_demo ? 'DEMO' : 'MODEL OUTPUT',
      ]),
    ].map((line) => line.map(escapeCsv).join(',')).join('\n')

    const blob = new Blob(['\uFEFF' + csv], {
      type: 'text/csv;charset=utf-8;',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'cohort_deidentified.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  const signOut = () => {
    logout()
    nav('/login')
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-teal-700">
              Research workspace
            </p>
            <h1 className="text-xl font-bold">Research overview</h1>
          </div>
          <div className="flex items-center gap-4">
            <span className="rounded-full bg-teal-50 px-3 py-2 text-xs font-semibold text-teal-800">
              Researcher access
            </span>
            <button
              onClick={signOut}
              className="text-sm font-semibold text-slate-600 hover:text-teal-800"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-7 px-6 py-8">
        <section>
          <h2 className="text-2xl font-bold">Consented research cohort</h2>
          <p className="mt-1 text-sm text-slate-500">
            Explore coded biomarker observations from patients who have provided research consent.
          </p>
        </section>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="rounded-xl border bg-white p-10 text-center text-sm text-slate-500">
            Loading research data...
          </div>
        ) : (
          <>
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { label: 'Coded cases', value: codedCases },
                { label: 'Biomarker observations', value: filteredRows.length },
                { label: 'Demo outputs', value: demoCount },
                { label: 'Validated predictions', value: validatedCount },
              ].map((stat) => (
                <div key={stat.label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {stat.label}
                  </p>
                  <p className="mt-2 text-3xl font-bold text-slate-800">
                    {stat.value}
                  </p>
                </div>
              ))}
            </section>

            <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-bold text-amber-900">DEMO DATA NOTICE</p>
              <p className="mt-1 text-sm text-amber-800">
                {demoCount} of {filteredRows.length} observations are illustrative demo outputs,
                not validated model predictions.
              </p>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b p-5">
                <div>
                  <h3 className="font-bold">Consented cohort</h3>
                  <p className="mt-1 text-xs text-slate-500">
                    Patient identifiers are coded; direct patient details are not displayed.
                  </p>
                </div>

                <select
                  value={cancerFilter}
                  onChange={(e) => setCancerFilter(e.target.value)}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                >
                  <option value="All">All cancer types</option>
                  {cancerTypes.map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-5 py-3">Coded case ID</th>
                      <th className="px-5 py-3">Cancer type</th>
                      <th className="px-5 py-3">Biomarker</th>
                      <th className="px-5 py-3">Illustrative score</th>
                      <th className="px-5 py-3">Output type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((r, i) => (
                      <tr key={`${r.coded_id}-${r.biomarker}-${i}`} className="border-t border-slate-100 hover:bg-slate-50">
                        <td className="px-5 py-4 font-semibold">{r.coded_id}</td>
                        <td className="px-5 py-4">{r.cancer}</td>
                        <td className="px-5 py-4 font-medium">{r.biomarker}</td>
                        <td className="px-5 py-4 tabular-nums">
  {displayScore(r.score).toFixed(0)}/100
</td>
                        <td className="px-5 py-4">
                          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${
                            r.is_demo
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-emerald-100 text-emerald-800'
                          }`}>
                            {r.is_demo ? 'DEMO' : 'MODEL OUTPUT'}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {filteredRows.length === 0 && (
                      <tr>
                        <td colSpan="5" className="px-5 py-10 text-center text-slate-500">
                          No cohort observations available for this filter.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t p-5">
                <p className="text-xs text-slate-500">
                  {filteredRows.length} observations · {codedCases} coded {codedCases === 1 ? 'case' : 'cases'} · {biomarkerCount} biomarker types
                </p>
                <button
                  onClick={exportCsv}
                  disabled={!filteredRows.length}
                  className="rounded-lg bg-teal-800 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-900 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Export de-identified CSV
                </button>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="mb-4">
                <h3 className="font-bold">Cohort score overview</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Descriptive average of displayed illustrative scores; not a clinical probability.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="rounded-lg bg-slate-50 p-4">
                  <p className="text-xs text-slate-500">Average illustrative score</p>
                  <p className="mt-1 text-2xl font-bold">{averageScore}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-4">
                  <p className="text-xs text-slate-500">Cancer types</p>
                  <p className="mt-1 text-2xl font-bold">{new Set(filteredRows.map((r) => r.cancer)).size}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-4">
                  <p className="text-xs text-slate-500">Biomarker types</p>
                  <p className="mt-1 text-2xl font-bold">{biomarkerCount}</p>
                </div>
              </div>
            </section>

            <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
              <div className="border-b p-5">
                <h3 className="font-bold">Audit activity</h3>
                <p className="mt-1 text-xs text-slate-500">
                  Recent recorded workspace activity. User roles are displayed instead of database IDs.
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-5 py-3">Time</th>
                      <th className="px-5 py-3">User role</th>
                      <th className="px-5 py-3">Action</th>
                      <th className="px-5 py-3">Target</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audit.map((event, i) => (
                      <tr key={`${event.timestamp}-${i}`} className="border-t border-slate-100">
                        <td className="whitespace-nowrap px-5 py-3 text-slate-500">
                          {formatTime(event.time || event.timestamp)}
                        </td>
                        <td className="px-5 py-3">
                          {USER_ROLES[event.user_id] || 'Authorized user'}
                        </td>
                        <td className="px-5 py-3 font-medium">{event.action}</td>
                        <td className="px-5 py-3">{event.target || '—'}</td>
                      </tr>
                    ))}
                    {audit.length === 0 && (
                      <tr>
                        <td colSpan="4" className="px-5 py-8 text-center text-slate-500">
                          No audit events available.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="border-t p-4 text-xs text-slate-500">
                Showing {audit.length} recorded events.
              </div>
            </section>
          </>
        )}

        <footer className="pb-4 text-center text-xs leading-6 text-slate-500">
          Research and decision-support only. Scores are based on RNA-derived proxy labels,
          not direct protein measurements. This tool is not validated for clinical use and
          does not replace pathologist judgment.
        </footer>
      </main>
    </div>
  )
}
