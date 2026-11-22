import { AppWindow, Clock, Download, File, FileText, Image, Monitor, Search, Share, type LucideIcon } from 'lucide-react'
// Imported module by module so the bundle carries only these parts' CSS
import { Stage } from './kit/stage'
import type { Act } from './kit/act'
import { Bar, Text, Window } from './kit/window'
import { Row } from './kit/parts/Row'
import { Field } from './kit/controls/Field'
import { Collapse } from './kit/motion/Collapse'
import './ro-hero.css'

// ro site hero (/pro): you remember a little, ro finds the file on this Mac.
// Story: ⌥R opens ro's panel → you type what you remember → three results with
// the reason each matched → ↵ opens the file, its window comes forward → ⌘W.
// Brand: cream + ink, selection is an ink surface. ro follows "ro pet viz": left-aligned ink layers,
// and it feels only through its eyes and layers: rest 기본 → typing 집중 → results 발견 → opened 풀어냄.
// As in the app (ro/pet_ui/pet.html), the panel sits on ro with its input at the bottom; results grow upward.

type Mood = 'rest' | 'focus' | 'found' | 'resolved'

type S = {
  focus: boolean     // ⌥R focuses ro's panel (always on screen: a reserved column, filled from frame one)
  typed: string
  shown: number      // result rows revealed
  picked: boolean    // first row pressed with ↵
  doc: boolean       // the opened PDF's window
  mood: Mood
}

const initial: S = { focus: false, typed: '', shown: 0, picked: false, doc: false, mood: 'rest' }
const QUERY = '/file contract pdf'
const RESULTS = [
  // Reasons in the app's own English (ro/pet_ui/i18n.js): what the viewer will see after installing
  { name: 'contract_final_v2.pdf', why: "Name starts with 'contract'" },
  { name: 'service_contract_signed.pdf', why: "Name contains 'contract'" },
  { name: 'Q3 contract review.pdf', why: "Name contains 'contract'" },
]
const POSTER: S = { focus: true, typed: QUERY, shown: 3, picked: true, doc: false, mood: 'found' }

async function script(a: Act<S>) {
  await a.wait(900)
  await a.key('alt+r')
  await a.set({ focus: true, mood: 'focus' })
  await a.wait(500)
  await a.type('typed', QUERY, { interval: 55 })
  await a.wait(250)
  await a.set({ shown: 1, mood: 'found' })
  await a.stagger([2, 3], (n) => a.set({ shown: n }), 110)
  await a.wait(1500)
  await a.key('enter')
  await a.set({ picked: true })
  await a.wait(350)
  await a.set({ doc: true, mood: 'resolved' })
  await a.wait(700)
  a.mark('payoff')
  await a.wait(1900)
  // A seen cause for the reset: close the document, then ro's panel
  await a.key('cmd+w')
  await a.set({ doc: false, mood: 'found' })
  await a.wait(500)
  await a.key('escape')
  await a.set({ focus: false, mood: 'rest', typed: '', shown: 0, picked: false })
  await a.wait(700)
}

// One icon family (Lucide), one stroke, one size per scene
function G({ icon: C, size = 14 }: { icon: LucideIcon; size?: number }) {
  return <C className="rh-glyph" size={size} strokeWidth={1.75} aria-hidden />
}

const SIDE: { icon: LucideIcon; label?: string; w?: number }[] = [
  { icon: Clock, w: 46 },
  { icon: AppWindow, w: 62 },
  { icon: Monitor, w: 40 },
  { icon: FileText, label: 'Documents' },
  { icon: Download, label: 'Downloads' },
]

export default function RoHero() {
  return (
    <Stage
      width={720}
      height={380}
      compact={{ below: 600, width: 358, height: 520 }}
      initial={initial}
      poster={POSTER}
      script={script}
      keys={{ wide: 'bottom-left', compact: 'top' }}
      className="rh"
    >
      {(s, _rect, layout) => (
        <>
          <Window
            title="Downloads"
            className="rh-finder"
            sidebarWidth={layout === 'compact' ? 0 : 150}
            sidebar={layout === 'compact' ? undefined : <Side />}
            receded={s.doc}
          >
            <div className="rh-files">
              <div className="rh-files__head"><span>Name</span></div>
              {[132, 96, 150, 84, 118, 104, 140, 90, 126, 110].map((w, i) => (
                <div key={i} className="rh-file">
                  <span className="rh-file__name"><G icon={i % 3 === 1 ? Image : File} /><Bar w={w} tone={3} /></span>
                </div>
              ))}
            </div>
          </Window>

          <Window title="contract_final_v2.pdf" className="rh-doc" data-show={s.doc || undefined}
            toolbar={<span className="rh-tools"><G icon={Search} /><G icon={Share} /></span>}>
            <div className="rh-page">
              <div className="rh-page__title">Service Agreement</div>
              {[260, 240, 270, 180, 0, 250, 262, 230, 150, 0, 244, 266, 210].map((w, i) =>
                w ? <Bar key={i} w={w} h={6} tone={2} /> : <span key={i} className="rh-page__gap" />,
              )}
            </div>
          </Window>

          <div className="rh-panel" data-focus={s.focus || undefined}>
            <div className="rh-results">
              {RESULTS.map((r, i) => (
                <Collapse key={r.name} open={s.shown > i}>
                  <Row
                    className="rh-row"
                    pad={8}
                    selected={i === 0}
                    data-picked={(i === 0 && s.picked) || undefined}
                    lead={<G icon={FileText} size={16} />}
                    title={<Text>{r.name}</Text>}
                    subtitle={<Text>{r.why}</Text>}
                  />
                </Collapse>
              ))}
            </div>
            <div className="rh-note">Searches stay on this Mac. Nothing is sent.</div>
            <Field
              className="rh-field"
              value={s.typed}
              placeholder="Log or find a file · / for commands"
              focused={s.focus && !s.picked}
              box={{ 'data-target': 'typed' }}
            />
          </div>

          <div className="rh-pet" data-mood={s.mood} aria-hidden>
            <div className="rh-pet__head">
              <span className="rh-pet__eye l" />
              <span className="rh-pet__eye r" />
              {/* 풀어냄's smiling eyes, from "ro pet viz" (outer radius 2u and 1.75u, 1u and 0.875u thick), in head units */}
              <svg className="rh-pet__smile" viewBox="0 0 19 8">
                <path d="M12 4.5A2 2 0 0 0 8 4.5H9A1 1 0 0 1 11 4.5Z" />
                <path d="M15.625 4.75A1.75 1.75 0 0 0 12.125 4.75H13A.875 .875 0 0 1 14.75 4.75Z" />
              </svg>
            </div>
            <div className="rh-pet__body" />
            <div className="rh-pet__base" />
          </div>
        </>
      )}
    </Stage>
  )
}

function Side() {
  return (
    <div className="rh-side">
      {SIDE.map((it, i) => (
        <div key={i} className="rh-side__item" data-on={i === SIDE.length - 1 || undefined}>
          <G icon={it.icon} />
          {it.label ? <span>{it.label}</span> : <Bar w={it.w ?? 50} tone={2} />}
        </div>
      ))}
    </div>
  )
}
