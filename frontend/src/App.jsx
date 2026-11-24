import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

async function request(path, token, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(`${API}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {}
    throw new Error(message);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/pdf")) return response.blob();
  if (type.includes("application/json")) return response.json();
  return response;
}

const dateLabel = (value) => value ? new Date(value).toLocaleString() : "—";
const shortDate = (value) => value ? new Date(value).toLocaleDateString() : "—";

function Icon({ children }) {
  return <span className="icon" aria-hidden="true">{children}</span>;
}

function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const data = await request("/auth/login", null, {
        method: "POST", body: JSON.stringify({ username, password })
      });
      
      onLogin(data);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <main className="login-shell">
      <section className="login-art">
        <div className="brand brand-light"><span className="brand-mark">S</span><span>SlideSense</span></div>
        <div className="login-art-copy">
          <span className="eyebrow light">DIGITAL PATHOLOGY WORKSPACE</span>
          <h1>Clarity for every<br />case you review.</h1>
          <p>A research and decision-support workspace for reviewing histopathology cases and biomarker profiles.</p>
        </div>
        <div className="login-art-footer">Secure workspace <span>•</span> Role-based access</div>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div className="login-mobile-brand brand"><span className="brand-mark">S</span><span>SlideSense</span></div>
          <span className="eyebrow">SECURE PORTAL ACCESS</span>
          <h2>Welcome back</h2>
          <p className="muted">Sign in with your assigned account to continue.</p>
          {error && <div className="alert error">{error}</div>}
          <label>Username<input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} placeholder="Enter your username" required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Enter your password" required /></label>
          <button className="btn primary full" disabled={busy}>{busy ? "Signing in…" : "Sign in"} <span>→</span></button>
          <div className="login-note"><Icon>▣</Icon> Your session is protected by role-based access.</div>
        </form>
      </section>
    </main>
  );
}

function PatientPortal({ auth, onLogout }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    let active = true;
    async function loadReports() {
      try {
        const data = await request("/me/reports", auth.token);
        if (active) setReports(data);
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }
    loadReports();
    return () => { active = false; };
  }, [auth.token]);

  const totalResults = reports.reduce(
    (sum, report) => sum + (report.predictions?.length || 0), 0
  );

  return (
    <div className="portal-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">S</span><span>SlideSense</span></div>
        <div className="side-label">MY HEALTHSPACE</div>
        <nav>
          <div className="nav-link active"><Icon>▦</Icon>My reports</div>
        </nav>
        <div className="sidebar-bottom">
          <div className="user-chip">
            <div className="avatar">{(auth.name || "P").slice(0, 1).toUpperCase()}</div>
            <div><strong>{auth.name || "Patient"}</strong><small>Patient</small></div>
          </div>
          <button className="nav-link logout" onClick={onLogout}><Icon>↪</Icon>Sign out</button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div><span className="top-kicker">PATIENT WORKSPACE</span><strong>My reports</strong></div>
          <div className="topbar-right"><span className="status-dot"></span><span>Secure session</span><span className="top-divider"></span><span className="top-user">{auth.name || "Patient"}</span></div>
        </header>

        <div className="content">
          {error && <div className="alert error">{error}</div>}

          <section>
            <div className="page-heading">
              <div>
                <span className="eyebrow">PERSONAL HEALTHSPACE</span>
                <h1>Welcome, {auth.name?.split(" ")[0] || "Patient"}</h1>
                <p>View reports that have been reviewed and signed off by your pathologist.</p>
              </div>
              <span className="count-pill">Patient access</span>
            </div>

            <div className="stat-grid patient-stat-grid">
              <Stat title="Available reports" value={reports.length} icon="▤" note="Signed-off cases only" />
              <Stat title="Biomarker results" value={totalResults} icon="◈" note="Results in your reports" />
            </div>

            <div className="section-heading">
              <div><h2>My pathology reports</h2><p>Your available signed-off case summaries</p></div>
            </div>

            {loading ? (
              <div className="panel portal-empty">Loading your reports...</div>
            ) : reports.length === 0 ? (
              <div className="panel portal-empty">
                <div className="portal-empty-icon">▤</div>
                <h3>No reports available yet</h3>
                <p>Reports will appear here after your pathologist reviews and signs off a case.</p>
              </div>
            ) : (
              <div className="portal-report-grid">
                {reports.map(report => (
                  <button className="portal-report-card" key={report.id} onClick={() => setSelected(report)}>
                    <div className="portal-report-top">
                      <span className="report-icon">▤</span>
                      <Status status={report.status} />
                    </div>
                    <strong>{report.code}</strong>
                    <span>{report.cancer}</span>
                    <small>Patient code: {report.patient}</small>
                    <small>Reviewed: {dateLabel(report.analysed_at)}</small>
                    <span className="text-btn">View report →</span>
                  </button>
                ))}
              </div>
            )}

            {selected && (
              <div className="panel patient-detail">
                <div className="panel-heading">
                  <div><h2>Report details · {selected.code}</h2><p>{selected.cancer}</p></div>
                  <button className="text-btn" onClick={() => setSelected(null)}>Close ×</button>
                </div>
                <div className="patient-report-body">
                  <div className="case-meta-grid">
                    <Meta label="Case ID" value={selected.code} />
                    <Meta label="Patient code" value={selected.patient} />
                    <Meta label="Case status" value={selected.status} />
                    <Meta label="Review decision" value={selected.decision} />
                  </div>

                  <h3>Biomarker profile</h3>
                  {selected.predictions?.some(p => p.is_demo) && (
                    <div className="demo-banner">
                      <strong>DEMO OUTPUT</strong>
                      <span>These illustrative scores are not validated clinical predictions.</span>
                    </div>
                  )}
                  {selected.predictions?.length ? (
                    <div className="biomarker-grid">
                      {selected.predictions.map(p => (
                        <div className="biomarker-card" key={p.biomarker}>
                          <div className="biomarker-top"><strong>{p.biomarker}</strong><span>{p.gene}</span></div>
                          <div className="score-line">
                            <strong>{Math.round(p.score * 100)}<small>%</small></strong>
                            <span className={`level ${p.level === "High" ? "high" : "low"}`}>{p.level}</span>
                          </div>
                          <div className="meter"><span style={{ width: `${p.score * 100}%` }} /></div>
                          <small className="model-note">{p.is_demo ? "Demo output" : p.model_name || "Model output"}</small>
                        </div>
                      ))}
                    </div>
                  ) : <p className="field-help">No biomarker results are available for this report.</p>}

                  <div className="patient-review-note">
                    <h3>Pathologist review</h3>
                    <p><strong>Decision:</strong> {selected.decision || "Not recorded"}</p>
                    <p><strong>Comment:</strong> {selected.comment || "No comment provided."}</p>
                    <p><strong>Next step:</strong> {selected.next_step || "Not specified."}</p>
                  </div>
                  <div className="disclaimer">
                    <strong>Research and decision-support only.</strong> Scores are based on RNA-derived proxy labels, not direct protein measurements. This tool is not validated for clinical use and does not replace pathologist judgment.
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function ResearcherPortal({ auth, onLogout }) {
  const [cohort, setCohort] = useState([]);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("All");

  useEffect(() => {
    let active = true;
    async function loadResearchData() {
      try {
        const [cohortData, auditData] = await Promise.all([
          request("/research/cohort", auth.token),
          request("/audit", auth.token)
        ]);
        if (active) {
          setCohort(cohortData);
          setAudit(auditData);
        }
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }
    loadResearchData();
    return () => { active = false; };
  }, [auth.token]);

  const cancerTypes = [...new Set(cohort.map(row => row.cancer))];
  const biomarkers = [...new Set(cohort.map(row => row.biomarker))];
  const visibleRows = filter === "All" ? cohort : cohort.filter(row => row.cancer === filter);
  const demoCount = cohort.filter(row => row.is_demo).length;
  const averageScore = cohort.length
    ? cohort.reduce((sum, row) => sum + row.score, 0) / cohort.length
    : 0;

  return (
    <div className="portal-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">S</span><span>SlideSense</span></div>
        <div className="side-label">RESEARCH WORKSPACE</div>
        <nav>
          <div className="nav-link active"><Icon>▦</Icon>Research overview</div>
          <div className="nav-link"><Icon>◈</Icon>Consented cohort</div>
          <div className="nav-link"><Icon>≡</Icon>Audit activity</div>
        </nav>
        <div className="sidebar-bottom">
          <div className="user-chip">
            <div className="avatar">{(auth.name || "R").slice(0, 1).toUpperCase()}</div>
            <div><strong>{auth.name || "Researcher"}</strong><small>Researcher</small></div>
          </div>
          <button className="nav-link logout" onClick={onLogout}><Icon>↪</Icon>Sign out</button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div><span className="top-kicker">RESEARCH WORKSPACE</span><strong>Research overview</strong></div>
          <div className="topbar-right"><span className="status-dot"></span><span>Secure session</span><span className="top-divider"></span><span className="top-user">{auth.name || "Researcher"}</span></div>
        </header>

        <div className="content">
          {error && <div className="alert error">{error}</div>}

          <section>
            <div className="page-heading">
              <div>
                <span className="eyebrow">CONSENTED RESEARCH DATA</span>
                <h1>Research overview</h1>
                <p>Explore coded biomarker records from patients who have provided research consent.</p>
              </div>
              <span className="count-pill">Coded cohort</span>
            </div>

            <div className="stat-grid">
              <Stat title="Cohort records" value={cohort.length} icon="▤" note="Biomarker observations" />
              <Stat title="Cancer types" value={cancerTypes.length} icon="◈" note="In the available cohort" />
              <Stat title="Biomarkers" value={biomarkers.length} icon="⌖" note="Distinct biomarker types" />
              <Stat title="Average score" value={`${Math.round(averageScore * 100)}%`} icon="∿" note="Across displayed records" />
            </div>

            {demoCount > 0 && (
              <div className="demo-banner research-demo">
                <strong>DEMO DATA</strong>
                <span>{demoCount} of {cohort.length} observations are demo outputs, not validated model predictions.</span>
              </div>
            )}

            <div className="panel">
              <div className="panel-heading">
                <div><h2>Consented cohort</h2><p>Patient identifiers are coded; direct patient details are not displayed.</p></div>
                <select className="research-filter" value={filter} onChange={e => setFilter(e.target.value)}>
                  <option value="All">All cancer types</option>
                  {cancerTypes.map(cancer => <option key={cancer} value={cancer}>{cancer}</option>)}
                </select>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Coded ID</th><th>Cancer type</th><th>Biomarker</th><th>Score</th><th>Output type</th></tr></thead>
                  <tbody>
                    {loading && <EmptyRow cols={5} text="Loading research cohort..." />}
                    {!loading && visibleRows.map((row, index) => (
                      <tr key={`${row.coded_id}-${row.biomarker}-${index}`}>
                        <td><strong className="code-text">{row.coded_id}</strong></td>
                        <td>{row.cancer}</td>
                        <td>{row.biomarker}</td>
                        <td>{Math.round(row.score * 100)}%</td>
                        <td><span className={`research-tag ${row.is_demo ? "demo" : "model"}`}>{row.is_demo ? "DEMO" : "Model output"}</span></td>
                      </tr>
                    ))}
                    {!loading && !visibleRows.length && <EmptyRow cols={5} text="No cohort records available for this filter." />}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="panel">
              <div className="panel-heading">
                <div><h2>Audit activity</h2><p>Recent recorded workspace activity.</p></div>
                <span className="count-pill">{audit.length} events</span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Time</th><th>User ID</th><th>Action</th><th>Target</th></tr></thead>
                  <tbody>
                    {loading && <EmptyRow cols={4} text="Loading audit activity..." />}
                    {!loading && audit.map((item, index) => (
                      <tr key={`${item.time}-${index}`}>
                        <td>{dateLabel(item.time)}</td>
                        <td>{item.user_id ?? "—"}</td>
                        <td>{item.action}</td>
                        <td>{item.target || "—"}</td>
                      </tr>
                    ))}
                    {!loading && !audit.length && <EmptyRow cols={4} text="No audit activity available." />}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="disclaimer">
              <strong>Research use only.</strong> Cohort scores may include demo outputs. RNA-derived proxy labels are not direct protein measurements and are not validated for clinical use.
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

function App() {
  const [auth, setAuth] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem("slidesense_auth") || "null"); } catch { return null; }
  });
  const [page, setPage] = useState("overview");
  const [patients, setPatients] = useState([]);
  const [cases, setCases] = useState([]);
  const [selectedCase, setSelectedCase] = useState(null);
  const [slides, setSlides] = useState([]);
  const [slidePreview, setSlidePreview] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [patientForm, setPatientForm] = useState({ code: "", age: "", sex: "Female" });
  const [caseForm, setCaseForm] = useState({ patient_code: "", cancer_type: "Lung adenocarcinoma (LUAD)" });
  const [review, setReview] = useState({ decision: "Agree", comment: "", next_step: "" });

  const token = auth?.token;
  const pendingCount = cases.filter(c => c.status === "Awaiting review").length;
  const signedCount = cases.filter(c => c.status === "Signed off").length;

  function handleLogin(data) {
    sessionStorage.setItem("slidesense_auth", JSON.stringify(data));
    setAuth(data);
  }
  function logout() {
    sessionStorage.removeItem("slidesense_auth");
    setAuth(null); setSelectedCase(null); setPatients([]); setCases([]);
  }

  async function loadData() {
    if (!token || auth?.role !== "pathologist") return;
    setLoading(true); setError("");
    try {
      const [p, c] = await Promise.all([
        request("/patients", token),
        request("/cases", token)
      ]);
      setPatients(p); setCases(c);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

    useEffect(() => {
    if (auth?.role === "pathologist") {
      loadData();
    } else {
      setPatients([]);
      setCases([]);
    }
  }, [token, auth?.role]);

  async function openCase(id) {
    setError(""); setNotice(""); setSlidePreview("");
    try {
      const data = await request(`/cases/${id}`, token);
      setSelectedCase(data);
      setReview({ decision: data.decision || "Agree", comment: data.comment || "", next_step: data.next_step || "" });
      const slideData = await request(`/cases/${id}/slides`, token);
      setSlides(slideData);
      setPage("workspace");
    } catch (err) { setError(err.message); }
  }

  async function createPatient(e) {
    e.preventDefault(); setError(""); setNotice("");
    try {
      await request("/patients", token, { method: "POST", body: JSON.stringify({ ...patientForm, age: Number(patientForm.age) }) });
      setPatientForm({ code: "", age: "", sex: "Female" });
      setNotice("Patient registered successfully.");
      await loadData();
    } catch (err) { setError(err.message); }
  }

  async function createCase(e) {
    e.preventDefault(); setError(""); setNotice("");
    try {
      const data = await request("/cases", token, { method: "POST", body: JSON.stringify(caseForm) });
      setNotice(`Case ${data.code} created successfully.`);
      setCaseForm({ ...caseForm, patient_code: "" });
      await loadData();
      await openCase(data.id);
    } catch (err) { setError(err.message); }
  }

  async function uploadSlide(e) {
    const file = e.target.files?.[0];
    if (!file || !selectedCase) return;
    setError(""); setNotice("");
    const form = new FormData(); form.append("file", file);
    try {
      await request(`/cases/${selectedCase.id}/slides`, token, { method: "POST", body: form });
      setNotice("Slide uploaded successfully.");
      setSlides(await request(`/cases/${selectedCase.id}/slides`, token));
    } catch (err) { setError(err.message); }
    e.target.value = "";
  }

  async function previewSlide(slide) {
    setError(""); setSlidePreview("");
    try {
      const info = await request(`/slides/${slide.id}/info`, token);
      const response = await fetch(`${API}/slides/${slide.id}/tile/0/0/0`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error("Could not load slide preview.");
      const blob = await response.blob();
      setSlidePreview(URL.createObjectURL(blob));
    } catch (err) { setError(err.message); }
  }

  async function runAnalysis() {
    if (!selectedCase) return;
    setError(""); setNotice("");
    try {
      const data = await request(`/cases/${selectedCase.id}/analyze`, token, { method: "POST" });
      setSelectedCase(data);
      setNotice("Demo analysis completed. Scores are illustrative and are not clinical predictions.");
      await loadData();
    } catch (err) { setError(err.message); }
  }

  async function submitReview(e) {
    e.preventDefault(); setError(""); setNotice("");
    try {
      const data = await request(`/cases/${selectedCase.id}/signoff`, token, {
        method: "POST", body: JSON.stringify(review)
      });
      setSelectedCase(data);
      setNotice("Case review saved and signed off.");
      await loadData();
    } catch (err) { setError(err.message); }
  }

  async function exportReport() {
    try {
      const blob = await request(`/cases/${selectedCase.id}/report`, token);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${selectedCase.code}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError(err.message); }
  }

  if (!auth) return <Login onLogin={handleLogin} />;
    if (auth.role === "patient") {
    return <PatientPortal auth={auth} onLogout={logout} />;
  }

  if (auth.role === "researcher") {
    return <ResearcherPortal auth={auth} onLogout={logout} />;
  }

  if (auth.role !== "pathologist") {
    return <Login onLogin={handleLogin} />;
  }

  const navItems = [
    ["overview", "▦", "Overview"],
    ["patients", "♙", "Patients"],
    ["cases", "▤", "Cases"],
    ["new-case", "＋", "Create case"]
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">S</span><span>SlideSense</span></div>
        <div className="side-label">WORKSPACE</div>
        <nav>
          {navItems.map(([key, icon, label]) => (
            <button key={key} className={`nav-link ${page === key || (key === "cases" && page === "workspace") ? "active" : ""}`} onClick={() => { setPage(key); setNotice(""); setError(""); }}>
              <Icon>{icon}</Icon>{label}
              {key === "cases" && pendingCount > 0 && <span className="nav-count">{pendingCount}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="user-chip"><div className="avatar">{(auth.name || "D").slice(0,1).toUpperCase()}</div><div><strong>{auth.name || auth.username}</strong><small>Pathologist</small></div></div>
          <button className="nav-link logout" onClick={logout}><Icon>↪</Icon>Sign out</button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div><span className="top-kicker">CLINICAL WORKSPACE</span><strong>{page === "workspace" ? selectedCase?.code || "Case workspace" : navItems.find(x => x[0] === page)?.[2] || "Overview"}</strong></div>
          <div className="topbar-right"><span className="status-dot"></span><span>System connected</span><span className="top-divider"></span><span className="top-user">{auth.name || "Pathologist"}</span></div>
        </header>

        <div className="content">
          {error && <div className="alert error"><span>{error}</span><button onClick={() => setError("")}>×</button></div>}
          {notice && <div className="alert success"><span>{notice}</span><button onClick={() => setNotice("")}>×</button></div>}

          {page === "overview" && <section>
            <div className="page-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h1>Good day, {auth.name?.split(" ")[0] || "Doctor"}</h1><p>Here is an overview of your pathology cases and review activity.</p></div><button className="btn primary" onClick={() => setPage("new-case")}>＋ Create new case</button></div>
            <div className="stat-grid">
              <Stat title="Registered patients" value={patients.length} icon="♙" note="Patient records" />
              <Stat title="Total cases" value={cases.length} icon="▤" note="Across all patients" />
              <Stat title="Awaiting review" value={pendingCount} icon="◷" note="Requires your attention" accent />
              <Stat title="Signed off" value={signedCount} icon="✓" note="Completed reviews" />
            </div>
            <div className="section-heading"><div><h2>Recent cases</h2><p>Your latest case activity</p></div><button className="text-btn" onClick={() => setPage("cases")}>View all cases →</button></div>
            <CaseTable cases={cases.slice(0,5)} onOpen={openCase} loading={loading} />
            <div className="notice-strip"><span className="notice-icon">ⓘ</span><div><strong>Research and decision-support tool</strong><p>Biomarker scores are research outputs and should be interpreted alongside histopathology findings and professional judgment.</p></div></div>
          </section>}

          {page === "patients" && <section>
            <div className="page-heading"><div><span className="eyebrow">PATIENT DIRECTORY</span><h1>Patients</h1><p>Manage coded patient records for your cases.</p></div><span className="count-pill">{patients.length} records</span></div>
            <div className="panel"><div className="panel-heading"><div><h2>Registered patients</h2><p>Patient identifiers are coded in this workspace.</p></div><button className="btn secondary" onClick={() => setPage("new-case")}>＋ New case</button></div>
              <div className="table-wrap"><table><thead><tr><th>Patient code</th><th>Age</th><th>Sex</th><th>Cases</th><th>Registered</th></tr></thead><tbody>
                {patients.map(p => <tr key={p.code}><td><strong className="code-text">{p.code}</strong></td><td>{p.age ?? "—"}</td><td>{p.sex || "—"}</td><td>{p.cases}</td><td>{shortDate(p.registered_at)}</td></tr>)}
                {!patients.length && <EmptyRow cols={5} text="No patient records found." />}
              </tbody></table></div>
            </div>
            <div className="panel form-panel"><div className="panel-heading"><div><h2>Register a patient</h2><p>Use a coded identifier rather than a patient name.</p></div></div>
              <form className="form-grid" onSubmit={createPatient}>
                <label>Patient code<input value={patientForm.code} onChange={e => setPatientForm({...patientForm, code:e.target.value})} placeholder="e.g. P-0142" required /></label>
                <label>Age<input type="number" min="0" max="120" value={patientForm.age} onChange={e => setPatientForm({...patientForm, age:e.target.value})} placeholder="Age" required /></label>
                <label>Sex<select value={patientForm.sex} onChange={e => setPatientForm({...patientForm, sex:e.target.value})}><option>Female</option><option>Male</option><option>Other</option><option>Not recorded</option></select></label>
                <div className="form-action"><button className="btn primary">Register patient</button></div>
              </form>
            </div>
          </section>}

          {page === "cases" && <section>
            <div className="page-heading"><div><span className="eyebrow">CASE MANAGEMENT</span><h1>All cases</h1><p>Open a case to review its slides, biomarker profile and status.</p></div><button className="btn primary" onClick={() => setPage("new-case")}>＋ Create new case</button></div>
            <CaseTable cases={cases} onOpen={openCase} loading={loading} />
          </section>}

          {page === "new-case" && <section>
            <div className="page-heading"><div><span className="eyebrow">CASE MANAGEMENT</span><h1>Create a case</h1><p>Associate a new pathology case with an existing coded patient.</p></div></div>
            <div className="panel form-panel narrow"><form className="stack-form" onSubmit={createCase}>
              <label>Patient code<select value={caseForm.patient_code} onChange={e => setCaseForm({...caseForm, patient_code:e.target.value})} required><option value="">Select a patient</option>{patients.map(p => <option key={p.code} value={p.code}>{p.code} · {p.age ?? "Age not recorded"} years</option>)}</select></label>
              <label>Cancer type<select value={caseForm.cancer_type} onChange={e => setCaseForm({...caseForm, cancer_type:e.target.value})}><option>Lung adenocarcinoma (LUAD)</option><option>Non-small cell lung cancer</option><option>Other</option></select></label>
              {!patients.length && <p className="field-help">Register a patient before creating a case.</p>}
              <button className="btn primary" disabled={!patients.length}>Create case</button>
            </form></div>
          </section>}

          {page === "workspace" && selectedCase && <section>
            <div className="breadcrumb"><button onClick={() => setPage("cases")}>Cases</button><span>/</span><strong>{selectedCase.code}</strong></div>
            <div className="page-heading workspace-heading"><div><span className="eyebrow">CASE WORKSPACE</span><h1>{selectedCase.code}</h1><p>{selectedCase.patient} <span className="bullet">•</span> {selectedCase.cancer}</p></div><Status status={selectedCase.status} /></div>
            <div className="case-meta-grid">
              <Meta label="Patient code" value={selectedCase.patient} /><Meta label="Cancer type" value={selectedCase.cancer} /><Meta label="Created / analysed" value={dateLabel(selectedCase.analysed_at)} /><Meta label="Case status" value={selectedCase.status} />
            </div>
            <div className="workspace-grid">
              <div className="workspace-main">
                <div className="panel">
                  <div className="panel-heading"><div><h2>Whole-slide image</h2><p>Upload and preview a supported histopathology slide.</p></div><label className="btn secondary upload-btn">↑ Upload slide<input type="file" accept=".svs,.tif,.tiff" onChange={uploadSlide} /></label></div>
                  {slidePreview ? <div className="slide-preview"><img src={slidePreview} alt="Whole-slide overview preview" /></div> : <div className="slide-empty"><div className="slide-placeholder">▧</div><strong>{slides.length ? "Slide uploaded" : "No slide uploaded yet"}</strong><p>{slides.length ? "Choose a slide below to load its overview preview." : "Upload an .svs, .tif or .tiff file to begin."}</p></div>}
                  {slides.length > 0 && <div className="slide-list">{slides.map(s => <div className="slide-row" key={s.id}><div className="file-icon">▧</div><div className="slide-file"><strong>{s.filename}</strong><small>{s.width.toLocaleString()} × {s.height.toLocaleString()} px</small></div><button className="text-btn" onClick={() => previewSlide(s)}>Preview</button></div>)}</div>}
                </div>
                <div className="panel">
                  <div className="panel-heading"><div><h2>Biomarker profile</h2><p>Predicted scores from the current analysis endpoint.</p></div><button className="btn primary" onClick={runAnalysis}>Run analysis</button></div>
                  {selectedCase.predictions?.length ? <>
                    {selectedCase.predictions.some(p => p.is_demo) && <div className="demo-banner"><strong>DEMO OUTPUT</strong><span>These scores are randomly generated placeholders, not real model predictions.</span></div>}
                    <div className="biomarker-grid">{selectedCase.predictions.map(p => <div className="biomarker-card" key={p.biomarker}><div className="biomarker-top"><strong>{p.biomarker}</strong><span>{p.gene}</span></div><div className="score-line"><strong>{Math.round(p.score * 100)}<small>%</small></strong><span className={`level ${p.level === "High" ? "high" : "low"}`}>{p.level}</span></div><div className="meter"><span style={{width:`${p.score * 100}%`}} /></div><small className="model-note">{p.model_name || "Model"} · {p.is_demo ? "Demo" : "Model output"}</small></div>)}</div>
                  </> : <div className="empty-inline"><span>◌</span><strong>No biomarker results available</strong><p>Run the analysis endpoint to populate this section. Current endpoint returns demo scores.</p></div>}
                </div>
              </div>
              <aside className="workspace-side">
                <div className="panel review-panel"><div className="panel-heading"><div><h2>Pathologist review</h2><p>Record your professional assessment.</p></div></div>
                  <form className="stack-form" onSubmit={submitReview}>
                    <label>Decision<select value={review.decision} onChange={e => setReview({...review, decision:e.target.value})}><option>Agree</option><option>Modify</option><option>Reject</option></select></label>
                    <label>Comment<textarea rows="4" value={review.comment} onChange={e => setReview({...review, comment:e.target.value})} placeholder="Add review comments…" /></label>
                    <label>Next step<textarea rows="3" value={review.next_step} onChange={e => setReview({...review, next_step:e.target.value})} placeholder="Recommended follow-up…" /></label>
                    <p className="field-help">A comment is required when you Modify or Reject.</p>
                    <button className="btn primary full">Save review & sign off</button>
                  </form>
                  {selectedCase.decision && <div className="signed-note"><strong>Current decision: {selectedCase.decision}</strong><small>Last status: {selectedCase.status}</small></div>}
                </div>
                <div className="panel report-panel"><div className="report-icon">▤</div><h3>Case report</h3><p>Export the current case summary and biomarker scores as a PDF.</p><button className="btn secondary full" onClick={exportReport}>↓ Export PDF report</button></div>
              </aside>
            </div>
            <div className="disclaimer"><strong>Research and decision-support only.</strong> Scores are based on RNA-derived proxy labels, not direct protein measurements. This tool is not validated for clinical use and does not replace pathologist judgment.</div>
          </section>}
        </div>
      </main>
    </div>
  );
}

function Stat({ title, value, icon, note, accent }) {
  return <div className={`stat-card ${accent ? "stat-accent" : ""}`}><div className="stat-top"><span>{title}</span><span className="stat-icon">{icon}</span></div><strong>{value}</strong><small>{note}</small></div>;
}
function Status({ status }) {
  const cls = status === "Signed off" ? "signed" : status === "Awaiting review" ? "review" : "waiting";
  return <span className={`status-pill ${cls}`}><i />{status || "Awaiting analysis"}</span>;
}
function Meta({ label, value }) {
  return <div className="meta-card"><small>{label}</small><strong>{value || "—"}</strong></div>;
}
function EmptyRow({ cols, text }) {
  return <tr><td colSpan={cols} className="empty-cell">{text}</td></tr>;
}
function CaseTable({ cases, onOpen, loading }) {
  return <div className="panel table-panel"><div className="table-wrap"><table><thead><tr><th>Case ID</th><th>Patient</th><th>Cancer type</th><th>Last analysed</th><th>Status</th><th></th></tr></thead><tbody>
    {loading && <EmptyRow cols={6} text="Loading cases…" />}
    {!loading && cases.map(c => <tr key={c.id}><td><strong className="code-text">{c.code}</strong></td><td>{c.patient}</td><td>{c.cancer}</td><td>{shortDate(c.analysed_at)}</td><td><Status status={c.status} /></td><td><button className="text-btn" onClick={() => onOpen(c.id)}>Open case →</button></td></tr>)}
    {!loading && !cases.length && <EmptyRow cols={6} text="No cases found. Create a case to get started." />}
  </tbody></table></div></div>;
}

export default App;
