// Applies the saved (or system) colour theme before the page paints, so there is no light/dark flash.
// Lives in its own file so the Content-Security-Policy does not need to allow inline scripts.
try {
  var t = localStorage.getItem('datanest-theme')
  if (t === 'dark' || (!t && matchMedia('(prefers-color-scheme: dark)').matches)) document.documentElement.classList.add('dark')
} catch (e) {}
