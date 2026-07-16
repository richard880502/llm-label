import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api, clearToken } from '../api/client'

export interface AuthUser { username: string; role: string }

interface AuthContextType {
  user: AuthUser | null
  loading: boolean
  logout: () => void
  setUser: (u: AuthUser | null) => void
}

const AuthContext = createContext<AuthContextType>({
  user: null, loading: true, logout: () => {}, setUser: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.me()
      .then(u => setUser(u))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const logout = () => {
    clearToken()
    setUser(null)
    window.location.href = '/login'
  }

  return (
    <AuthContext.Provider value={{ user, loading, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
