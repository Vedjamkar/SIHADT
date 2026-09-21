import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
// Design system, in cascade order: tokens define the custom properties that
// base and components both consume, so it must come first.
import './styles/tokens.css'
import './styles/base.css'
import './styles/components.css'
import './styles/views.css'
import './styles/workspace.css'
import './styles/organizer.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
