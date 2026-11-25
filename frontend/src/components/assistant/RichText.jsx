// Tiny, safe formatter for assistant replies: paragraphs, "-"/"*"/"1." lists and **bold**. Never uses innerHTML.
function Inline({ text }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((p, i) => (p.startsWith('**') && p.endsWith('**') && p.length > 4 ? <strong key={i}>{p.slice(2, -2)}</strong> : <span key={i}>{p}</span>))
}

export default function RichText({ text }) {
  const blocks = []
  let list = null
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const m = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line)
    if (m) {
      if (!list) { list = []; blocks.push({ list }) }
      list.push(m[1])
    } else {
      list = null
      if (line.trim()) blocks.push({ p: line })
    }
  }
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((b, i) =>
        b.list ? (
          <ul key={i} className="list-disc space-y-1 pl-5">{b.list.map((li, j) => <li key={j}><Inline text={li} /></li>)}</ul>
        ) : (
          <p key={i}><Inline text={b.p} /></p>
        ),
      )}
    </div>
  )
}
