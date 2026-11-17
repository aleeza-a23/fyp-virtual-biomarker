const { app, BrowserWindow } = require('electron')
const { spawn } = require('child_process')
const path = require('path')

let backend
function startBackend() {
  // Dev only: uses the project's Python environment. Packaging replaces this later.
  const py = 'D:\\FYP\\fyp_env\\Scripts\\python.exe'
  backend = spawn(py, ['-m', 'uvicorn', 'app.main:app', '--port', '8000'], { cwd: path.join(__dirname, '..', 'backend') })
  backend.stderr.on('data', d => console.log('[backend]', d.toString()))
}
function createWindow() {
  const win = new BrowserWindow({ width: 1400, height: 900, title: 'SlideSense' })
  setTimeout(() => win.loadURL('http://localhost:5173'), 2500) // wait for backend and Vite to be ready
}
app.whenReady().then(() => { startBackend(); createWindow() })
app.on('window-all-closed', () => { if (backend) backend.kill(); app.quit() })
