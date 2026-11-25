import { initializeApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider } from 'firebase/auth'

const cfg = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

export const isAuthConfigured = Boolean(cfg.apiKey && cfg.authDomain && cfg.projectId && cfg.appId)

// The Firebase web config is public by design; access is enforced by the backend verifying ID tokens.
export const auth = isAuthConfigured ? getAuth(initializeApp(cfg)) : null
export const googleProvider = new GoogleAuthProvider()
googleProvider.setCustomParameters({ prompt: 'select_account' })
