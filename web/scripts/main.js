// Placeholder page behaviour. Nothing is wired to a backend yet.

function section() {
  return document.body.dataset.section || 'home';
}

function loader() {
  const dots = document.createElement('span');
  dots.className = 'dots';
  dots.setAttribute('role', 'status');
  dots.setAttribute('aria-label', 'Working');
  for (let i = 0; i < 3; i++) dots.appendChild(document.createElement('span'));
  return dots;
}

// Summarize: ask the local model about this section and show what comes back.
function initSummarize() {
  const button = document.getElementById('summarize');
  const body = document.querySelector('.summary-body');
  if (!button || !body) return;

  button.addEventListener('click', async () => {
    button.disabled = true;
    body.classList.remove('meta');
    body.replaceChildren(loader());

    try {
      const res = await fetch(`/api/summarize?section=${encodeURIComponent(section())}`,
                              { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        body.textContent = data.summary || '(the model returned nothing)';
      } else {
        // Show the reason rather than a spinner that never stops.
        body.classList.add('meta');
        body.textContent = `${data.error || 'failed'}${data.hint ? ' — ' + data.hint : ''}`;
      }
    } catch (err) {
      body.classList.add('meta');
      body.textContent = 'could not reach the app';
    } finally {
      button.disabled = false;
    }
  });
}

// Refresh: run this section's ingest, then reload so the page shows it.
function initRefresh() {
  const button = document.getElementById('refresh');
  if (!button) return;

  button.addEventListener('click', async () => {
    if (button.classList.contains('spinning')) return;
    button.classList.add('spinning');
    button.setAttribute('aria-busy', 'true');

    try {
      const res = await fetch(`/api/refresh?section=${encodeURIComponent(section())}`,
                              { method: 'POST' });
      if (res.ok) {
        window.location.reload();
        return;
      }
      const data = await res.json().catch(() => ({}));
      button.title = `refresh failed: ${data.error || res.status}`;
    } catch (err) {
      button.title = 'could not reach the app';
    }
    button.classList.remove('spinning');
    button.removeAttribute('aria-busy');
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
