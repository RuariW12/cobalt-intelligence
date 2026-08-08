// Applied from <head>, synchronously, before the body paints — otherwise a
// stored day-mode preference flashes the dark theme on every page load.
// Deliberately not in main.js, which is deferred and therefore too late.
(function () {
  try {
    if (localStorage.getItem('cobalt-theme') === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    }
  } catch (e) {
    /* private mode or storage disabled — night mode is the default anyway */
  }
})();
