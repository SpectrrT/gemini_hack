// Temporary: lets the owner compare the style options on the real pages. Open either page with
// ?style=quiet | blueprint | playground | sheet (sheet = the current default). The choice is kept for the
// browser tab, so the link between the two pages keeps it. Remove this file and its script tag once a style is chosen.
(() => {
  const OPTIONS = {quiet: '/web/styles/quiet.css', blueprint: '/web/styles/blueprint.css', playground: '/web/styles/playground.css', sheet: '/web/wordless.css'};
  let pick = new URLSearchParams(location.search).get('style');
  try { if (pick) sessionStorage.setItem('wordless.style', pick); else pick = sessionStorage.getItem('wordless.style'); } catch (e) {}
  const link = document.querySelector('link[rel=stylesheet][href^="/web/"]');
  if (link && OPTIONS[pick]) link.href = OPTIONS[pick];
})();
