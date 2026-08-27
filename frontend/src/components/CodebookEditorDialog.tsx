import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  value: string
  onChange: (value: string) => void
  correctedExamples: number
  dirty: boolean
  saving: boolean
  message: string | null
  onSave: () => Promise<void>
}

export default function CodebookEditorDialog({
  open,
  onOpenChange,
  value,
  onChange,
  correctedExamples,
  dirty,
  saving,
  message,
  onSave,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-5xl h-[88vh] flex flex-col gap-0 p-0 overflow-hidden">
        <DialogHeader className="shrink-0 border-b px-6 py-4">
          <div className="flex items-start justify-between gap-4 pr-8">
            <div>
              <DialogTitle>分類規則 / Codebook</DialogTitle>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                專心在這裡編輯分類判斷原則。平台 API 與 MCP Agent 都會使用同一份規則。
              </p>
            </div>
            <Badge variant={dirty ? 'outline' : 'secondary'}>{dirty ? '尚未儲存' : '已儲存'}</Badge>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-6">
          <div className="grid min-h-full gap-5 lg:grid-cols-[minmax(0,1fr)_15rem]">
            <div className="flex min-h-[34rem] flex-col rounded-2xl border border-teal-200 bg-teal-50/30 p-4 dark:border-teal-900 dark:bg-teal-950/10">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">完整規則</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">描述標籤判斷、模糊案例、例外與優先順序。</p>
                </div>
                <span className="text-xs font-mono text-muted-foreground">{value.length.toLocaleString()} / 12,000</span>
              </div>

              <textarea
                autoFocus
                value={value}
                onChange={event => onChange(event.target.value)}
                maxLength={12000}
                placeholder="例如：\n- 當文字主要在詢問退款進度時，標記為 refund_status。\n- 如果同時包含配送延遲與退款要求，以使用者最主要的訴求為準。\n- 不確定時保留 reason 說明判斷依據。"
                className="min-h-[30rem] flex-1 resize-none rounded-xl border border-input bg-card px-4 py-3 text-sm leading-7 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-500/30"
              />
            </div>

            <aside className="space-y-3">
              <div className="rounded-2xl border border-border bg-muted/30 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">目前專案</p>
                <div className="mt-3 space-y-3 text-sm">
                  <div>
                    <p className="font-medium">人工修正案例</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{correctedExamples} 筆，可依模型 Few-shot 設定提供給分類模型。</p>
                  </div>
                  <div>
                    <p className="font-medium">規則使用範圍</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">平台 API 與 MCP Agent 共用，不需要分開維護。</p>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-border p-4">
                <p className="text-sm font-medium">撰寫建議</p>
                <div className="mt-2 space-y-2 text-xs leading-5 text-muted-foreground">
                  <p>先寫清楚每個標籤「什麼情況要選」。</p>
                  <p>再補充容易混淆的邊界案例與優先順序。</p>
                  <p>如果規則修改後要重跑，回到自動分類主畫面直接開始即可。</p>
                </div>
              </div>

              {message && (
                <p className={`rounded-xl border px-3 py-2 text-xs ${
                  message.startsWith('儲存失敗')
                    ? 'border-destructive/20 bg-destructive/5 text-destructive'
                    : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-400'
                }`}>
                  {message}
                </p>
              )}
            </aside>
          </div>
        </div>

        <DialogFooter className="shrink-0 border-t px-6 py-3">
          <div className="mr-auto text-xs text-muted-foreground">
            {dirty ? '尚有未儲存變更；直接開始分類時也會先自動儲存。' : '目前使用的 Codebook 已是最新版本。'}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>完成</Button>
          <Button onClick={onSave} disabled={!dirty || saving}>
            {saving ? '儲存中…' : '儲存規則'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
