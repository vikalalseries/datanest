import axios from 'axios'
import { auth } from './firebase'

export const api = axios.create({
  baseURL: `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api`,
  timeout: 30000,
})

api.interceptors.request.use(async (config) => {
  const user = auth?.currentUser
  if (user) {
    // getIdToken() returns a cached token and refreshes it automatically when it is about to expire
    config.headers.Authorization = `Bearer ${await user.getIdToken()}`
  }
  return config
})

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    if (error.response?.status === 401 && auth?.currentUser) {
      // token rejected even after refresh: end the session so the UI returns to login
      await auth.signOut()
    }
    return Promise.reject(error)
  },
)

/** Turn any axios error into a short, user-safe message. */
export function errorMessage(error) {
  const apiMsg = error?.response?.data?.error?.message
  if (apiMsg) return apiMsg
  if (error?.code === 'ECONNABORTED') return 'The request timed out. Please try again.'
  if (!error?.response) return 'Cannot reach the DataNest server. Check your connection and try again.'
  return 'Something went wrong. Please try again.'
}

export const getMe = () => api.get('/auth/me').then((r) => r.data)
