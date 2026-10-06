import { useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getProjectSchema, getTendency, type TendencyReport } from '../api/annotation'
import { labelDisplayName } from '../components/AnnotationControls'
import HeaderUserMenu from '../components/HeaderUserMenu'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type Reviewer = TendencyReport['reviewers'][number]

const pct = (v: number | null | undefined, digits = 0) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)
const fmtP = (p: number | null) => (p == null ? '—' : p < 0.001 ? '< 0.001' : p.toFixed(3))

/* ---- tooltip -------------------------------------------------------- */
type Tip = { x: number; y: number; content: ReactNode } | null

function useTip() {
  const [tip, setTip] = useState<Tip>(null)
  const bind = (content: ReactNode) => ({
    onMouseMove: (e: React.MouseEvent) => setTip({ x: e.clientX, y: e.clientY, content }),
    onMouseLeave: () => setTip(null),
  })
  const node = tip && (
    <div className="fixed z-50 pointer-events-none rounded-md border bg-popover text-popover-foreground shadow-md px-2.5 py-1.5 text-xs"
      style={{ left: tip.x + 12, top: tip.y + 12 }}>{tip.content}</div>
  )
  return { bind, node }
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map(i => (
        <span key={i.label} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  )
}

/* ---- 100% stacked bar with a 2px gap between segments ---------------- */
function StackBar({ parts, bind }: {
  parts: { label: string; value: number; color: string }[]
  bind: ReturnType<typeof useTip>['bind']
}) {
  const total = parts.reduce((a, p) => a + p.value, 0)
  if (!total) return <div className="h-3 rounded bg-muted" />
  return (
    <div className="flex h-3 gap-[2px]">
      {parts.filter(p => p.value > 0).map((p, i, arr) => (
        <div key={p.label} style={{ width: `${p.value / total * 100}%`, background: p.color }}
          className={`h-full ${i === 0 ? 'rounded-l' : ''} ${i === arr.length - 1 ? 'rounded-r' : ''}`}
          {...bind(<>{p.label}：{p.value}（{pct(p.value / total)}）</>)} />
      ))}
    </div>
  )
}

/* ---- coverage heat strip: share of each row span a reviewer has done -- */
function CoverageLanes({ data, bind }: { data: TendencyReport; bind: ReturnType<typeof useTip>['bind'] }) {
  const bins = data.coverage
  if (!bins.length) return null
  const lanes = [
    ...data.reviewers.map((r, i) => ({ key: r.name, label: r.name, color: ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)'][i % 4] })),
    { key: '__pending', label: '待審', color: 'var(--viz-muted)' },
  ]
  const share = (cell: (typeof bins)[number], key: string) =>
    cell.total === 0 ? 0 : (key === '__pending' ? cell.pending : cell.by[key] ?? 0) / cell.total
  return (
    <div className="space-y-1.5">
      {lanes.map(lane => (
        <div key={lane.key} className="grid grid-cols-[4rem_1fr] items-center gap-3">
          <span className="text-xs truncate">{lane.label}</span>
          <div className="flex h-5 gap-px">
            {bins.map(cell => {
              const f = share(cell, lane.key)
              const count = lane.key === '__pending' ? cell.pending : cell.by[lane.key] ?? 0
              return (
                <div key={cell.start} className="flex-1 rounded-[2px] bg-muted/60 overflow-hidden relative"
                  {...bind(<>第 {cell.start}–{cell.end} 列<br />{lane.label}：{count} / {cell.total} 筆（{pct(f)}）</>)}>
                  <div className="absolute inset-x-0 bottom-0" style={{ height: `${f * 100}%`, background: lane.color }} />
                </div>
              )
            })}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[4rem_1fr] gap-3 text-[10px] text-muted-foreground">
        <span />
        <div className="flex justify-between"><span>第 {bins[0].start} 列</span><span>第 {bins[bins.length - 1].end} 列</span></div>
      </div>
    </div>
  )
}

/* ---- paired horizontal bars: AI vs final per label ------------------- */
function PairedBars({ labels, name, bind }: {
  labels: TendencyReport['labels']; name: (id: string) => string; bind: ReturnType<typeof useTip>['bind']
}) {
  const rows = [...labels].sort((a, b) => (b.final_rate ?? 0) - (a.final_rate ?? 0))
  const max = Math.max(0.01, ...rows.flatMap(l => [l.ai_rate ?? 0, l.final_rate ?? 0]))
  return (
    <div className="space-y-2">
      {rows.map(l => (
        <div key={l.label_id} className="grid grid-cols-[8rem_1fr] items-center gap-3 text-xs"
          {...bind(<>
            <b>{name(l.label_id)}</b><br />AI 選用 {pct(l.ai_rate, 1)}<br />最終選用 {pct(l.final_rate, 1)}
          </>)}>
          <span className="truncate">{name(l.label_id)}</span>
          <div className="space-y-[2px]">
            {([['ai_rate', 'var(--viz-1)'], ['final_rate', 'var(--viz-2)']] as const).map(([key, color]) => (
              <div key={key} className="flex items-center gap-2">
                <div className="h-2 rounded-r-[4px]" style={{ width: `${(l[key] ?? 0) / max * 100}%`, background: color, minWidth: 2 }} />
                <span className="text-muted-foreground tabular-nums">{pct(l[key])}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/* ---- diverging bars: removed (left) vs added (right) ------------------ */
function DivergingBars({ labels, name, bind }: {
  labels: TendencyReport['labels']; name: (id: string) => string; bind: ReturnType<typeof useTip>['bind']
}) {
  const rows = [...labels]
    .filter(l => l.added_by_review + l.removed_by_review > 0)
    .sort((a, b) => (b.added_by_review + b.removed_by_review) - (a.added_by_review + a.removed_by_review))
  const max = Math.max(1, ...rows.flatMap(l => [l.added_by_review, l.removed_by_review]))
  if (!rows.length) return <p className="text-xs text-muted-foreground">審查沒有改動任何標籤。</p>
  return (
    <div className="space-y-1.5">
      {rows.map(l => (
        <div key={l.label_id} className="grid grid-cols-[8rem_1fr_4.5rem] items-center gap-3 text-xs"
          {...bind(<>
            <b>{name(l.label_id)}</b><br />被補上 +{l.added_by_review}　被移除 −{l.removed_by_review}<br />
            Holm 校正後 p = {fmtP(l.p_adjusted)}
          </>)}>
          <span className="truncate">{name(l.label_id)}</span>
          <div className="grid grid-cols-2 items-center">
            <div className="flex justify-end border-r border-border pr-px">
              <div className="h-2.5 rounded-l-[4px]" style={{ width: `${l.removed_by_review / max * 100}%`, background: 'var(--viz-neg)' }} />
            </div>
            <div className="pl-px">
              <div className="h-2.5 rounded-r-[4px]" style={{ width: `${l.added_by_review / max * 100}%`, background: 'var(--viz-1)' }} />
            </div>
          </div>
          <span className="text-right tabular-nums">
            {l.p_adjusted != null && l.p_adjusted < 0.05
              ? <span className="font-medium text-foreground">偏{l.direction === 'added' ? '補上' : '移除'} ＊</span>
              : <span className="text-muted-foreground">無明顯偏向</span>}
          </span>
        </div>
      ))}
    </div>
  )
}

function Explain({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group rounded-lg border bg-muted/30 px-3 py-2 text-xs">
      <summary className="cursor-pointer select-none text-muted-foreground group-open:text-foreground">
        ⓘ {title}
      </summary>
      <div className="mt-2 space-y-1.5 leading-relaxed text-muted-foreground">{children}</div>
    </details>
  )
}

function effectSize(phi: number | null) {
  if (phi == null) return '—'
  return phi < 0.1 ? '幾乎沒差' : phi < 0.3 ? '差異小' : phi < 0.5 ? '差異中等' : '差異大'
}

type Insight = { tone: 'warn' | 'info' | 'ok'; title: string; detail: string }

function buildInsights(data: TendencyReport, name: (id: string) => string): Insight[] {
  const out: Insight[] = []
  for (const r of data.reviewers) {
    const decided = r.approved + r.corrected
    if (r.model_written > 0 && r.reviewed > 0) {
      const share = r.model_written / r.reviewed
      if (share >= 0.2) out.push({
        tone: 'warn',
        title: `${r.name} 審過的資料中，${pct(share)} 的結果是 AI 模型寫入`,
        detail: `共 ${r.model_written} / ${r.reviewed} 筆。這些筆數算「已審」，但不能當成人工獨立判斷。`,
      })
    }
    if (decided >= 30 && r.approve_rate != null && r.approve_rate >= 0.95) out.push({
      tone: 'warn',
      title: `${r.name} 幾乎全部直接核准（${pct(r.approve_rate)}）`,
      detail: '核准率過高可能代表快速放行，建議抽樣複核確認。',
    })
    if (decided >= 30 && r.correction_rate != null && r.correction_rate >= 0.5) out.push({
      tone: 'info',
      title: `${r.name} 有 ${pct(r.correction_rate)} 的資料被修正`,
      detail: '修正比例高：可能是這段資料 AI 表現較差，也可能是審查標準較嚴。',
    })
  }
  if (!data.reviewer_ranges_overlap && data.reviewers.length > 1) out.push({
    tone: 'info',
    title: '審查者各自處理不同區段的資料，只有少數區段重疊',
    detail: '所以無法判斷差異來自人還是資料；要比較審查者，需讓他們審同一批資料。',
  })
  const sig = data.labels.filter(l => l.p_adjusted != null && l.p_adjusted < 0.05)
  const missed = [...sig].filter(l => l.direction === 'added').sort((a, b) => b.added_by_review - a.added_by_review)[0]
  const extra = [...sig].filter(l => l.direction === 'removed').sort((a, b) => b.removed_by_review - a.removed_by_review)[0]
  if (missed) out.push({
    tone: 'info',
    title: `AI 最常漏標「${name(missed.label_id)}」`,
    detail: `審查時被補上 ${missed.added_by_review} 次，被移除只有 ${missed.removed_by_review} 次。可考慮在 Codebook 補強這個標籤的判斷說明。`,
  })
  if (extra) out.push({
    tone: 'info',
    title: `AI 最常多標「${name(extra.label_id)}」`,
    detail: `審查時被移除 ${extra.removed_by_review} 次，被補上只有 ${extra.added_by_review} 次。`,
  })
  if (!out.length) out.push({ tone: 'ok', title: '目前沒有明顯的傾向問題', detail: '審查者之間與 AI 對各標籤的處理沒有顯著偏向。' })
  return out
}

const TONE = {
  warn: { icon: '⚠', cls: 'border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700/50' },
  info: { icon: 'ℹ', cls: 'border-sky-300 bg-sky-50 dark:bg-sky-900/20 dark:border-sky-700/50' },
  ok: { icon: '✓', cls: 'border-emerald-300 bg-emerald-50 dark:bg-emerald-900/20 dark:border-emerald-700/50' },
} as const

export default function TendencyPage() {
  const pid = Number(useParams().projectId)
  const navigate = useNavigate()
  const { bind, node } = useTip()
  const { data: schema } = useQuery({ queryKey: ['annotation-schema', pid], queryFn: () => getProjectSchema(pid) })
  const { data } = useQuery({ queryKey: ['tendency', pid], queryFn: () => getTendency(pid) })
  const name = (id: string) => (schema ? labelDisplayName(schema, id) : id)

  return (
    <div className="viz min-h-screen">
      <header className="border-b px-6 py-2.5 flex items-center gap-2">
        <Button variant="ghost" size="sm" className="px-2" onClick={() => navigate(`/projects/${pid}`)}>← 返回專案</Button>
        <h1 className="text-sm font-semibold flex-1">標注傾向</h1>
        <HeaderUserMenu />
      </header>
      <main className="max-w-5xl mx-auto px-4 py-6 space-y-8">
        {!data || !schema ? <p className="text-sm text-muted-foreground">載入中…</p> : (
          <>
            <p className="text-xs text-muted-foreground">
              由現有審查紀錄計算，不需額外標注。已審 {data.reviewed_total} 筆、待審 {data.pending_total} 筆。
              ＊ 表示 Holm 校正後 p &lt; 0.05。
            </p>

            <section className="space-y-2">
              <h2 className="text-sm font-medium">重點發現</h2>
              {buildInsights(data, name).map(i => (
                <div key={i.title} className={`rounded-lg border px-3.5 py-2.5 flex gap-3 ${TONE[i.tone].cls}`}>
                  <span className="text-base leading-6">{TONE[i.tone].icon}</span>
                  <div className="space-y-0.5">
                    <p className="text-sm font-medium">{i.title}</p>
                    <p className="text-xs text-muted-foreground">{i.detail}</p>
                  </div>
                </div>
              ))}
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-medium">誰審了哪些資料</h2>
              <p className="text-xs text-muted-foreground">每一格是一段連續列號，柱高 = 該段資料中此人已審的比例。</p>
              <Card><CardContent className="py-3">
                <CoverageLanes data={data} bind={bind} />
              </CardContent></Card>
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-medium">審查者</h2>
              <Legend items={[
                { label: '直接核准', color: 'var(--viz-1)' }, { label: '修正', color: 'var(--viz-2)' },
                { label: '未確定', color: 'var(--viz-4)' },
              ]} />
              <div className="grid gap-3 sm:grid-cols-2">
                {data.reviewers.map(r => {
                  const untouched = r.reviewed - r.human_edited - r.model_written - r.uncertain
                  return (
                    <Card key={r.name}><CardContent className="py-4 space-y-3">
                      <div className="flex items-baseline justify-between">
                        <span className="font-medium">{r.name}</span>
                        <span className="text-xs text-muted-foreground">{r.reviewed} 筆</span>
                      </div>
                      <div className="space-y-1">
                        <StackBar bind={bind} parts={[
                          { label: '直接核准', value: r.approved, color: 'var(--viz-1)' },
                          { label: '修正', value: r.corrected, color: 'var(--viz-2)' },
                          { label: '未確定', value: r.uncertain, color: 'var(--viz-4)' },
                        ]} />
                        <p className="text-xs text-muted-foreground">
                          核准率 {pct(r.approve_rate)}
                          {r.approve_ci && <>（95% 信賴區間 {pct(r.approve_ci[0])}–{pct(r.approve_ci[1])}）</>}
                        </p>
                      </div>
                      <div className="space-y-1">
                        <p className="text-xs font-medium">結果由誰寫入</p>
                        <StackBar bind={bind} parts={[
                          { label: '人工編輯', value: r.human_edited, color: 'var(--viz-3)' },
                          { label: 'AI 模型寫入', value: r.model_written, color: 'var(--viz-7)' },
                          { label: '沿用 AI 預測', value: Math.max(0, untouched), color: 'var(--viz-muted)' },
                        ]} />
                        <Legend items={[
                          { label: `人工編輯 ${r.human_edited}`, color: 'var(--viz-3)' },
                          { label: `AI 模型寫入 ${r.model_written}`, color: 'var(--viz-7)' },
                          { label: `沿用 AI 預測 ${Math.max(0, untouched)}`, color: 'var(--viz-muted)' },
                        ]} />
                      </div>
                    </CardContent></Card>
                  )
                })}
              </div>

              {data.reviewer_comparisons.map(c => {
                const significant = c.p_adjusted != null && c.p_adjusted < 0.05
                return (
                  <div key={`${c.a}-${c.b}`} className="rounded-lg border px-3 py-2 text-xs space-y-0.5">
                    <p className="font-medium">
                      {c.a} vs {c.b}：核准／修正比例
                      {significant ? '有顯著差異' : '沒有顯著差異'}（{effectSize(c.effect_phi)}）
                    </p>
                    <p className="text-muted-foreground">
                      p = {fmtP(c.p_adjusted)}，φ = {c.effect_phi ?? '—'}；兩人共同審過的區段只佔 {pct(c.shared_share)}
                      {c.confounded && '，所以這個差異不能直接歸因於審查者，可能只是資料不同。'}
                    </p>
                  </div>
                )
              })}
              <Explain title="核准率的「95% 信賴區間」和這個比較是什麼意思？">
                <p><b>95% 信賴區間</b>：核准率是用已審的樣本算出來的，樣本越少越不準。區間是「真實核准率大概落在這個範圍」，區間越窄越可信。</p>
                <p><b>卡方檢定</b>：檢查兩位審查者「核准 vs 修正」的比例差異，是真的不同，還是只是隨機波動。p 越小代表越不可能只是巧合，一般 p &lt; 0.05 才算顯著。</p>
                <p><b>φ（效果量）</b>：p 值只說「有沒有差」，φ 說「差多少」。約 0.1 為小、0.3 為中、0.5 以上為大。資料筆數多時，很小的差異也會顯著，所以要一起看 φ。</p>
                <p><b>Holm 校正</b>：同時做很多次比較時，偶然「中獎」的機會會變高，Holm 會把 p 值調高以避免誤判。</p>
              </Explain>
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-medium">各標籤：AI 選用率 vs 審查後選用率</h2>
              <Legend items={[{ label: 'AI 預測', color: 'var(--viz-1)' }, { label: '審查後最終結果', color: 'var(--viz-2)' }]} />
              <Card><CardContent className="py-4">
                <PairedBars labels={data.labels} name={name} bind={bind} />
              </CardContent></Card>
            </section>

            <section className="space-y-3">
              <h2 className="text-sm font-medium">審查改動方向（{data.compared_rows} 筆，相關性被改判 {data.relevance_flips} 筆）</h2>
              <Legend items={[{ label: 'AI 多標（被移除）', color: 'var(--viz-neg)' }, { label: 'AI 漏標（被補上）', color: 'var(--viz-1)' }]} />
              <Card><CardContent className="py-4 space-y-3">
                <DivergingBars labels={data.labels} name={name} bind={bind} />
                <p className="text-[11px] text-muted-foreground">
                  每個標籤用 McNemar 精確檢定「補上」與「移除」是否不對稱，並以 Holm 法校正多重比較。
                </p>
              </CardContent></Card>
              <Explain title="「偏補上／偏移除 ＊」是怎麼判斷的？">
                <p>對每個標籤，只看審查時<b>有改動</b>的資料：AI 漏標而被補上的有 a 筆，AI 多標而被移除的有 b 筆。</p>
                <p>如果 AI 的錯誤只是隨機的，a 和 b 應該差不多。<b>McNemar 精確檢定</b>檢查 a、b 的差距是否大到不像巧合；顯著（校正後 p &lt; 0.05）就代表 AI 對這個標籤有<b>系統性偏向</b>：偏補上＝常漏標，偏移除＝常多標。</p>
                <p>只改動幾筆時檢定力很低，會顯示「無明顯偏向」，這不代表 AI 沒有偏向，只是證據不足。</p>
              </Explain>
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">表格檢視</summary>
                <table className="w-full mt-2">
                  <thead><tr className="text-left text-muted-foreground">
                    <th className="py-1">標籤</th><th>AI</th><th>最終</th><th>補上</th><th>移除</th><th>校正 p</th>
                  </tr></thead>
                  <tbody>
                    {data.labels.map(l => (
                      <tr key={l.label_id} className="border-t">
                        <td className="py-1">{name(l.label_id)}</td><td>{pct(l.ai_rate, 1)}</td><td>{pct(l.final_rate, 1)}</td>
                        <td>+{l.added_by_review}</td><td>−{l.removed_by_review}</td><td>{fmtP(l.p_adjusted)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </section>
          </>
        )}
        {data && (
          <Explain title="這些統計的限制">
            <p>• 這裡只比較「已審」的資料；待審資料不在統計內，若審查順序不是隨機，結果可能有偏差。</p>
            <p>• 審查者之間的比較需要審過<b>同類資料</b>。各自處理不同區段時，差異可能來自資料難度而不是人，頁面會標示這一點。</p>
            <p>• 統計顯著不等於重要，也不等於因果。要確認審查者之間是否真的一致，需要讓兩人獨立標注同一批資料。</p>
          </Explain>
        )}
        {node}
      </main>
    </div>
  )
}
