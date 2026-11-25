import { useAuth } from '../context/AuthContext'
import { Spinner } from '../components/Spinner'

export default function Profile() {
  const { profile, signOut } = useAuth()
  if (!profile) return <Spinner />
  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold max-lg:sr-only">Profile</h1>
      <div className="card mt-6 flex items-center gap-4 p-5">
        {profile.avatar_url ? (
          <img src={profile.avatar_url} alt="" referrerPolicy="no-referrer" className="h-16 w-16 rounded-full" />
        ) : (
          <span className="grid h-16 w-16 place-items-center rounded-full bg-muted text-xl font-semibold">{profile.email[0].toUpperCase()}</span>
        )}
        <div className="min-w-0">
          <p className="truncate text-lg font-medium">{profile.full_name || 'Unnamed user'}</p>
          <p className="truncate text-sm text-soft">{profile.email}</p>
          <p className="mt-1 text-xs text-soft">Member since {new Date(profile.created_at).toLocaleDateString()}</p>
        </div>
      </div>
      <button className="btn-ghost mt-4" onClick={signOut}>Sign out</button>
    </div>
  )
}
