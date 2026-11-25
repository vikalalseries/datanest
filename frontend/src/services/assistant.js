import { api } from './api'

const d = (p) => p.then((r) => r.data)

export const sendChat = (message, history) => d(api.post('/ai/chat', { message, history }, { timeout: 150000 }))
export const confirmAction = (action) => d(api.post('/ai/chat/confirm', { action }))

export const SUGGESTIONS = [
  'How many applications have I sent?',
  'Show all internships I applied for this month.',
  'Which companies haven’t responded?',
  'Find applications with upcoming deadlines.',
  'Show my expenses above 500 rupees.',
  'Find duplicate records.',
  'Summarize my job application activity.',
  'Create a new sheet for my project tasks.',
]

export const HISTORY_TURNS = 10

/** Last few text turns for context (never tables/proposals, never error bubbles). */
export function toHistory(messages) {
  return messages
    .filter((m) => !m.error && m.text)
    .slice(-HISTORY_TURNS)
    .map((m) => ({ role: m.role, text: m.text.slice(0, 4000) }))
}
