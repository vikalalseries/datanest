// Dotted background: a grid of dots that move away from the pointer and spring back.
// Lives in its own file so the Content-Security-Policy does not need to allow inline scripts.
(function () {
  var canvas = document.getElementById('bg')
  if (!canvas || !canvas.getContext) return
  var ctx = canvas.getContext('2d')

  var GAP = 32          // distance between dots
  var RADIUS = 110      // pointer influence
  var SPRING = 0.06     // pull back to the home position
  var FRICTION = 0.82   // calms the motion
  var PUSH = 3.2        // how hard the pointer shoves a dot
  var BASE = 1.1        // resting dot size
  var GROW = 1.8        // extra size next to the pointer

  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches
  var dpr = 1, w = 0, h = 0
  var dots = []
  var pointer = { x: -9999, y: -9999 }
  var ink = [17, 24, 39], accent = [79, 70, 229]
  var raf = 0, running = false

  // "17 24 39" (the app stores colours as space separated channels) -> [17, 24, 39]
  function channels(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim().split(/\s+/).map(Number)
    return v.length === 3 && v.every(function (n) { return !isNaN(n) }) ? v : fallback
  }
  function readColours() {
    ink = channels('--ink', ink)
    accent = channels('--brand', accent)
    draw()
  }

  function build() {
    dpr = Math.min(window.devicePixelRatio || 1, 2)
    w = window.innerWidth
    h = window.innerHeight
    canvas.width = Math.round(w * dpr)
    canvas.height = Math.round(h * dpr)
    canvas.style.width = w + 'px'
    canvas.style.height = h + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    dots = []
    var cols = Math.ceil(w / GAP) + 1
    var rows = Math.ceil(h / GAP) + 1
    var offX = (w - (cols - 1) * GAP) / 2
    var offY = (h - (rows - 1) * GAP) / 2
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var hx = offX + c * GAP, hy = offY + r * GAP
        dots.push({ hx: hx, hy: hy, x: hx, y: hy, vx: 0, vy: 0, f: 0 })
      }
    }
    draw()
  }

  function step() {
    var moving = false
    for (var i = 0; i < dots.length; i++) {
      var d = dots[i]
      var dx = d.x - pointer.x, dy = d.y - pointer.y
      var dist = Math.sqrt(dx * dx + dy * dy)
      var f = 0
      if (dist < RADIUS && dist > 0.001) {
        f = 1 - dist / RADIUS
        d.vx += (dx / dist) * f * PUSH
        d.vy += (dy / dist) * f * PUSH
      }
      d.vx += (d.hx - d.x) * SPRING
      d.vy += (d.hy - d.y) * SPRING
      d.vx *= FRICTION
      d.vy *= FRICTION
      d.x += d.vx
      d.y += d.vy
      d.f = f
      if (f > 0 || Math.abs(d.vx) > 0.02 || Math.abs(d.vy) > 0.02 || Math.abs(d.hx - d.x) > 0.05 || Math.abs(d.hy - d.y) > 0.05) moving = true
    }
    return moving
  }

  function draw() {
    ctx.clearRect(0, 0, w, h)
    for (var i = 0; i < dots.length; i++) {
      var d = dots[i]
      var near = d.f > 0
      var c = near ? accent : ink
      var a = near ? 0.35 + d.f * 0.5 : 0.16
      ctx.fillStyle = 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'
      ctx.beginPath()
      ctx.arc(d.x, d.y, BASE + d.f * GROW, 0, 6.2832)
      ctx.fill()
    }
  }

  function loop() {
    var moving = step()
    draw()
    if (moving && !document.hidden) raf = requestAnimationFrame(loop)
    else running = false
  }
  function start() {
    if (reduced || running || document.hidden) return
    running = true
    raf = requestAnimationFrame(loop)
  }

  function move(e) {
    pointer.x = e.clientX
    pointer.y = e.clientY
    start()
  }
  function leave() {
    pointer.x = pointer.y = -9999
    start()
  }

  window.addEventListener('pointermove', move, { passive: true })
  window.addEventListener('pointerdown', move, { passive: true })
  window.addEventListener('pointerup', function (e) { if (e.pointerType === 'touch') leave() }, { passive: true })
  window.addEventListener('pointercancel', leave, { passive: true })
  document.addEventListener('pointerleave', leave)
  window.addEventListener('blur', leave)
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { cancelAnimationFrame(raf); running = false } else start()
  })
  var resizeTimer = 0
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(build, 120)
  })

  // the theme toggle adds or removes the "dark" class on <html>
  new MutationObserver(readColours).observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })

  ink = channels('--ink', ink)
  accent = channels('--brand', accent)
  build()
})()
