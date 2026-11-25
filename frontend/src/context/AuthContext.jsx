import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { onAuthStateChanged, signInWithPopup, signOut as fbSignOut } from 'firebase/auth'
import { auth, googleProvider, isAuthConfigured } from '../services/firebase'
import { getMe, errorMessage } from '../services/api'

const AuthContext = createContext(null)

// DEV ONLY: mirror of the backend AUTH_DISABLED switch. Never enabled in a production build.
const DEV_NO_AUTH = import.meta.env.VITE_AUTH_DISABLED === 'true' && !import.meta.env.PROD
const DEV_USER = { uid: 'dev-user', email: 'dev@localhost.test', displayName: 'Dev User', photoURL: null }

export function AuthProvider({ children }) {
  const [user, setUser] = useState(DEV_NO_AUTH ? DEV_USER : null)
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(isAuthConfigured && !DEV_NO_AUTH)
  const [profileError, setProfileError] = useState(null)

  useEffect(() => {
    if (!auth || DEV_NO_AUTH) return
    return onAuthStateChanged(auth, (u) => {
      setUser(u)
      setLoading(false)
    })
  }, [])

  const uid = user?.uid
  useEffect(() => {
    if (!uid) {
      setProfile(null)
      setProfileError(null)
      return
    }
    let cancelled = false
    getMe()
      .then((p) => !cancelled && (setProfile(p), setProfileError(null)))
      .catch((e) => !cancelled && setProfileError(errorMessage(e)))
    return () => {
      cancelled = true
    }
  }, [uid])

  const signInWithGoogle = useCallback(async () => {
    try {
      await signInWithPopup(auth, googleProvider)
      return { error: null }
    } catch (e) {
      // user closing the popup is not an error worth showing
      if (e?.code === 'auth/popup-closed-by-user' || e?.code === 'auth/cancelled-popup-request') return { error: null }
      if (e?.code === 'auth/popup-blocked') return { error: 'Your browser blocked the sign-in popup. Allow popups for this site and try again.' }
      if (e?.code === 'auth/unauthorized-domain') return { error: 'This domain is not authorized for sign-in in Firebase yet.' }
      if (e?.code === 'auth/operation-not-allowed') return { error: 'Google sign-in is not enabled in Firebase yet.' }
      return { error: 'Google sign-in failed. Please try again.' }
    }
  }, [])
  const signOut = useCallback(() => (DEV_NO_AUTH ? Promise.resolve() : fbSignOut(auth)), [])

  // Shape kept compatible with the UI: `session.user` carries display name / photo.
  const session = useMemo(
    () => (user ? { user: { id: user.uid, email: user.email, user_metadata: { full_name: user.displayName, avatar_url: user.photoURL } } } : null),
    [user],
  )

  const value = useMemo(
    () => ({ session, profile, loading, profileError, signInWithGoogle, signOut, configured: isAuthConfigured || DEV_NO_AUTH }),
    [session, profile, loading, profileError, signInWithGoogle, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
