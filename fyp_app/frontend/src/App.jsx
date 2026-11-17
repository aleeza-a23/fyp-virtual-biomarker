import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Login from './pages/Login'
import DoctorDashboard from './pages/DoctorDashboard'
import CaseDetail from './pages/CaseDetail'
import PatientHome from './pages/PatientHome'
import ResearcherHome from './pages/ResearcherHome'

const HOME = { pathologist: '/doctor', researcher: '/researcher', patient: '/patient' }

function Guard({ role, children }) {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== role) return <Navigate to={HOME[user.role]} replace />
  return children
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login home={HOME} />} />
          <Route path="/doctor" element={<Guard role="pathologist"><DoctorDashboard /></Guard>} />
          <Route path="/doctor/case/:id" element={<Guard role="pathologist"><CaseDetail /></Guard>} />
          <Route path="/researcher" element={<Guard role="researcher"><ResearcherHome /></Guard>} />
          <Route path="/patient" element={<Guard role="patient"><PatientHome /></Guard>} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}