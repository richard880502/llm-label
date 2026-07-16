import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import QRCode from 'react-qr-code'
import { api, User } from '../api/client'
import { useAuth } from '../context/AuthContext'
import HeaderUserMenu from '../components/HeaderUserMenu'

export default function UsersPage() {
  const navigate = useNavigate()
  const { user: me } = useAuth()

  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [showCreate, setShowCreate] = useState(false)
  const [createUsername, setCreateUsername] = useState('')
  const [createPassword, setCreatePassword] = useState('')
  const [createRole, setCreateRole] = useState('reviewer')
  const [createEmail, setCreateEmail] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [emailTarget, setEmailTarget] = useState<User | null>(null)
  const [emailValue, setEmailValue] = useState('')
  const [settingEmail, setSettingEmail] = useState(false)
  const [emailError, setEmailError] = useState<string | null>(null)

  const [totpQr, setTotpQr] = useState<{ uri: string; username: string } | null>(null)

  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetPassword, setResetPasswordVal] = useState('')
  const [resetting, setResetting] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    api.listUsers().then(setUsers).catch(e => setError(e.message)).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!createUsername.trim() || !createPassword) return
    setCreating(true); setCreateError(null)
    try {
      await api.createUser(createUsername.trim(), createPassword, createRole, createEmail.trim())
      setShowCreate(false); setCreateUsername(''); setCreatePassword(''); setCreateRole('reviewer'); setCreateEmail('')
      load()
    } catch (e: any) { setCreateError(e.message) }
    finally { setCreating(false) }
  }

  const handleSetEmail = async () => {
    if (!emailTarget) return
    setSettingEmail(true); setEmailError(null)
    try {
      const updated = await api.setUserEmail(emailTarget.id, emailValue.trim())
      setUsers(prev => prev.map(u => u.id === updated.id ? updated : u))
      setEmailTarget(null); setEmailValue('')
    } catch (e: any) { setEmailError(e.message) }
    finally { setSettingEmail(false) }
  }

  const handleRoleChange = async (u: User, newRole: string) => {
    try {
      const updated = await api.updateUserRole(u.id, newRole)
      setUsers(prev => prev.map(x => x.id === u.id ? { ...x, role: updated.role } : x))
    } catch (e: any) { setError(e.message) }
  }

  const handleDelete = async (u: User) => {
    if (!window.confirm(`確定要刪除「${u.username}」嗎？`)) return
    try { await api.deleteUser(u.id); load() }
    catch (e: any) { setError(e.message) }
  }

  const handleReset = async () => {
    if (!resetTarget || !resetPassword) return
    setResetting(true); setResetError(null)
    try {
      await api.resetPassword(resetTarget.id, resetPassword)
      setResetTarget(null); setResetPasswordVal('')
    } catch (e: any) { setResetError(e.message) }
    finally { setResetting(false) }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors">
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 shadow-sm">
        <div className="max-w-4xl mx-auto px-6 py-3 flex items-center gap-3">
          <button onClick={() => navigate('/')} className="text-sm text-gray-400 dark:text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">←</button>
          <span className="text-gray-200 dark:text-gray-700">/</span>
          <h1 className="text-sm font-semibold text-gray-900 dark:text-gray-100 flex-1">使用者管理</h1>
          <HeaderUserMenu />
          <button onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
            + 新增使用者
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 rounded-lg text-sm">{error}</div>
        )}

        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
          {loading ? (
            <div className="text-center py-16 text-gray-400 dark:text-gray-500">載入中…</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">帳號</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Google Email</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-16">2FA</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-28">角色</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-36">建立時間</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-52">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {users.map(u => (
                  <tr key={u.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                    <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                      {u.username}
                      {u.username === me?.username && (
                        <span className="ml-2 text-xs text-gray-400 dark:text-gray-500">（我）</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 text-xs">
                      {u.email
                        ? <span className="text-green-600 dark:text-green-400">{u.email}</span>
                        : <span className="text-gray-300 dark:text-gray-600">未設定</span>}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {u.totp_enabled
                        ? <span className="text-green-600 dark:text-green-400 font-medium">✓ 啟用</span>
                        : <span className="text-gray-300 dark:text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {u.username === me?.username ? (
                        <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
                          {u.role === 'admin' ? '管理員' : '複查員'}
                        </span>
                      ) : (
                        <select
                          value={u.role}
                          onChange={e => handleRoleChange(u, e.target.value)}
                          className="text-xs border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          <option value="reviewer">複查員</option>
                          <option value="admin">管理員</option>
                        </select>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400 font-mono text-xs">{u.created_at?.slice(0, 10)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 flex-wrap">
                        <button onClick={() => { setEmailTarget(u); setEmailValue(u.email || ''); setEmailError(null) }}
                          className="text-xs px-2.5 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                          設定 Email
                        </button>
                        <button onClick={() => { setResetTarget(u); setResetPasswordVal(''); setResetError(null) }}
                          className="text-xs px-2.5 py-1 border border-gray-300 dark:border-gray-600 rounded text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                          重設密碼
                        </button>
                        {u.totp_enabled ? (
                          <button onClick={async () => {
                            if (!window.confirm(`確定要停用「${u.username}」的雙驗證嗎？`)) return
                            try {
                              await api.adminDisableTotp(u.id)
                              setUsers(prev => prev.map(x => x.id === u.id ? { ...x, totp_enabled: 0 } : x))
                            } catch (e: any) { setError(e.message) }
                          }}
                            className="text-xs px-2.5 py-1 border border-orange-200 dark:border-orange-900 rounded text-orange-500 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/30 transition-colors">
                            停用 2FA
                          </button>
                        ) : (
                          <button onClick={async () => {
                            try {
                              const res = await api.adminEnableTotp(u.id)
                              setUsers(prev => prev.map(x => x.id === u.id ? { ...x, totp_enabled: 1 } : x))
                              setTotpQr({ uri: res.uri, username: u.username })
                            } catch (e: any) { setError(e.message) }
                          }}
                            className="text-xs px-2.5 py-1 border border-blue-200 dark:border-blue-900 rounded text-blue-500 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors">
                            啟用 2FA
                          </button>
                        )}
                        <button onClick={() => handleDelete(u)}
                          disabled={u.username === me?.username}
                          className="text-xs px-2.5 py-1 border border-red-200 dark:border-red-900 rounded text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors">
                          刪除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* Create user modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-sm p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">新增使用者</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">帳號</label>
                <input type="text" value={createUsername} onChange={e => setCreateUsername(e.target.value)}
                  placeholder="輸入帳號" autoFocus
                  className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">密碼</label>
                <input type="password" value={createPassword} onChange={e => setCreatePassword(e.target.value)}
                  placeholder="至少 4 個字元"
                  className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">角色</label>
                <select value={createRole} onChange={e => setCreateRole(e.target.value)}
                  className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="reviewer">複查員</option>
                  <option value="admin">管理員</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Google Email <span className="font-normal text-gray-400 dark:text-gray-500">（選填，供 Google 登入綁定）</span>
                </label>
                <input type="email" value={createEmail} onChange={e => setCreateEmail(e.target.value)}
                  placeholder="user@gmail.com"
                  className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              {createError && <p className="text-sm text-red-600 dark:text-red-400">{createError}</p>}
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => { setShowCreate(false); setCreateError(null) }}
                className="flex-1 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                取消
              </button>
              <button onClick={handleCreate} disabled={!createUsername.trim() || !createPassword || creating}
                className="flex-1 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {creating ? '建立中…' : '建立'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Set email modal */}
      {emailTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-sm p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">設定 Google Email</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">帳號：<strong className="text-gray-900 dark:text-gray-100">{emailTarget.username}</strong></p>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Google Email</label>
              <input type="email" value={emailValue} onChange={e => setEmailValue(e.target.value)}
                placeholder="user@gmail.com" autoFocus
                className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">留空可清除綁定</p>
              {emailError && <p className="text-sm text-red-600 dark:text-red-400 mt-2">{emailError}</p>}
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => { setEmailTarget(null); setEmailError(null) }}
                className="flex-1 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                取消
              </button>
              <button onClick={handleSetEmail} disabled={settingEmail}
                className="flex-1 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {settingEmail ? '儲存中…' : '儲存'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Admin TOTP QR modal */}
      {totpQr && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-sm p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">雙驗證已啟用</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              請將此 QR code 傳給 <strong className="text-gray-900 dark:text-gray-100">{totpQr.username}</strong>，讓他用 Google Authenticator 掃描：
            </p>
            <div className="flex justify-center p-4 bg-white rounded-xl border border-gray-200 dark:border-gray-600">
              <QRCode value={totpQr.uri} size={180} />
            </div>
            <p className="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
              使用者掃描完成前請勿關閉。未掃描前登入將被鎖定。
            </p>
            <button onClick={() => setTotpQr(null)}
              className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
              完成
            </button>
          </div>
        </div>
      )}

      {/* Reset password modal */}
      {resetTarget && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-sm p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">重設密碼</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">帳號：<strong className="text-gray-900 dark:text-gray-100">{resetTarget.username}</strong></p>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">新密碼</label>
              <input type="password" value={resetPassword} onChange={e => setResetPasswordVal(e.target.value)}
                placeholder="至少 4 個字元" autoFocus
                className="w-full border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {resetError && <p className="text-sm text-red-600 dark:text-red-400 mt-2">{resetError}</p>}
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => { setResetTarget(null); setResetError(null) }}
                className="flex-1 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                取消
              </button>
              <button onClick={handleReset} disabled={!resetPassword || resetting}
                className="flex-1 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                {resetting ? '更新中…' : '確認重設'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
