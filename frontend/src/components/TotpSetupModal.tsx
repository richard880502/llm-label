import { useEffect, useState } from 'react'
import QRCode from 'react-qr-code'
import { api } from '../api/client'

interface Props {
  open: boolean
  onClose: () => void
}

export default function TotpSetupModal({ open, onClose }: Props) {
  const [enabled, setEnabled] = useState(false)
  const [step, setStep] = useState<'status' | 'qr' | 'confirm' | 'done'>('status')
  const [uri, setUri] = useState('')
  const [secret, setSecret] = useState('')
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setStep('status'); setError(null); setCode('')
    api.totpStatus().then(r => setEnabled(r.enabled)).catch(() => {})
  }, [open])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  const handleSetup = async () => {
    setLoading(true); setError(null)
    try {
      const res = await api.totpSetup()
      setUri(res.uri); setSecret(res.secret)
      setStep('qr')
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleConfirm = async () => {
    if (code.length !== 6) return
    setLoading(true); setError(null)
    try {
      await api.totpConfirm(code)
      setEnabled(true); setStep('done')
    } catch (e: any) { setError(e.message); setCode('') }
    finally { setLoading(false) }
  }

  const handleDisable = async () => {
    if (!window.confirm('確定要停用雙驗證嗎？')) return
    setLoading(true); setError(null)
    try {
      await api.totpDisable()
      setEnabled(false); setStep('status')
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">雙重驗證（2FA）</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none">✕</button>
        </div>

        {step === 'status' && (
          <div className="space-y-4">
            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium ${enabled ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'}`}>
              <span>{enabled ? '✓ 已啟用' : '未啟用'}</span>
            </div>
            {enabled ? (
              <button onClick={handleDisable} disabled={loading}
                className="w-full py-2 border border-red-300 dark:border-red-800 text-red-600 dark:text-red-400 rounded-lg text-sm hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 transition-colors">
                停用雙驗證
              </button>
            ) : (
              <button onClick={handleSetup} disabled={loading}
                className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors">
                {loading ? '產生中…' : '啟用雙驗證'}
              </button>
            )}
          </div>
        )}

        {step === 'qr' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">用 Google Authenticator 或 Authy 掃描下方 QR code：</p>
            <div className="flex justify-center p-4 bg-white rounded-xl border border-gray-200 dark:border-gray-600">
              <QRCode value={uri} size={180} />
            </div>
            <details className="text-xs text-gray-400 dark:text-gray-500 cursor-pointer">
              <summary>無法掃描？手動輸入金鑰</summary>
              <p className="mt-1 font-mono break-all select-all bg-gray-50 dark:bg-gray-700 p-2 rounded">{secret}</p>
            </details>
            <button onClick={() => setStep('confirm')}
              className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
              已掃描，下一步
            </button>
          </div>
        )}

        {step === 'confirm' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">輸入 App 上顯示的 6 位數驗證碼確認設定：</p>
            <input
              type="text" inputMode="numeric" value={code} maxLength={6} autoFocus
              onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="000000"
              className="w-full text-center text-2xl font-mono tracking-[0.5em] border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-300 dark:placeholder-gray-600 rounded-lg px-3 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button onClick={handleConfirm} disabled={code.length !== 6 || loading}
              className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors">
              {loading ? '驗證中…' : '確認啟用'}
            </button>
            <button onClick={() => setStep('qr')}
              className="w-full py-1.5 text-sm text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
              ← 返回 QR code
            </button>
          </div>
        )}

        {step === 'done' && (
          <div className="space-y-4 text-center">
            <div className="text-4xl">✅</div>
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">雙驗證已啟用</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">下次登入時需要輸入 App 上的驗證碼</p>
            <button onClick={onClose}
              className="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
              完成
            </button>
          </div>
        )}

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>
    </div>
  )
}
