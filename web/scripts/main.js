// Placeholder page behaviour. Nothing is wired to a backend yet.

// Summarize: swap the summary body for a three-dot loader. There is no model
// connected, so the loader runs indefinitely by design — reload to reset.
function initSummarize() {
  const button = document.getElementById('summarize');
  const body = document.querySelector('.summary-body');
  if (!button || !body) return;

  button.addEventListener('click', () => {
    button.disabled = true;

    const dots = document.createElement('span');
    dots.className = 'dots';
    dots.setAttribute('role', 'status');
    dots.setAttribute('aria-label', 'Generating summary');
    for (let i = 0; i < 3; i++) {
      dots.appendChild(document.createElement('span'));
    }

    body.classList.remove('meta');
    body.replaceChildren(dots);
  });
}

// Refresh: spin the icon while an ingest runs. No ETL is connected yet, so it
// spins indefinitely — removing .spinning is what returns it to resting grey.
function initRefresh() {
  const button = document.getElementById('refresh');
  if (!button) return;

  button.addEventListener('click', () => {
    if (button.classList.contains('spinning')) return;
    button.classList.add('spinning');
    button.setAttribute('aria-busy', 'true');
  });
}

// Day/night toggle. The icon swap is done in CSS off the data-theme attribute;
// this only flips the attribute, remembers it, and keeps the label truthful.
function initTheme() {
  const button = document.getElementById('theme-toggle');
  if (!button) return;

  const root = document.documentElement;
  const isLight = () => root.getAttribute('data-theme') === 'light';

  const relabel = () => {
    const next = isLight() ? 'night' : 'day';
    button.title = `Switch to ${next} mode`;
    button.setAttribute('aria-label', `Switch to ${next} mode`);
  };

  relabel();

  button.addEventListener('click', () => {
    const light = isLight();
    if (light) {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', 'light');
    }
    try {
      localStorage.setItem('cobalt-theme', light ? 'dark' : 'light');
    } catch (e) {
      /* not persisted; the toggle still works for this page view */
    }
    relabel();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initSummarize();
  initRefresh();
  initTheme();
});
