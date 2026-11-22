// Mounts the /pro hero demo into #ro-hero. Without JS the page keeps its static ro figure.
// Pause (WCAG 2.2.2): the stage moves for more than 5 seconds, so the viewer can stop it.
// Paused, the stage shows its still poster; Play remounts it at the story's start.
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { StillContext } from './kit/reduced-motion'
import RoHero from './RoHero'

const LABEL = 'Animation: pressing Option-R opens ro\'s panel, "/file contract pdf" is typed, three matching PDFs appear, each with why it matched, and Enter opens contract_final_v2.pdf. The panel notes that searches stay on this Mac and nothing is sent.'

function Host() {
  const [paused, setPaused] = useState(false)
  const [osReduced, setOsReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setOsReduced(mq.matches)
    update()
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return (
    <>
      <div role="img" aria-label={LABEL}>
        <StillContext.Provider value={paused}>
          <RoHero key={paused ? 'still' : 'live'} />
        </StillContext.Provider>
      </div>
      {!osReduced && (
        <button type="button" className="demo-toggle" aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
          {paused ? 'Play animation' : 'Pause animation'}
        </button>
      )}
    </>
  )
}

const el = document.getElementById('ro-hero')
if (el) {
  el.replaceChildren()
  el.classList.add('is-live')
  createRoot(el).render(<Host />)
}
