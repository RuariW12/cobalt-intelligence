# Conventions

## Styling

- **No inline styling.** No `<style>` blocks in HTML, no `style=` attributes.
  All CSS lives in `styles/`.
- `styles/main.css` holds the base theme. Page-specific rules get their own file
  in `styles/`, linked alongside `main.css`.
- Every page links the stylesheet as `/styles/main.css` (absolute, so it
  resolves from nested routes like `/econ/metals`).

## Look and feel

Deliberately plain — close to raw HTML.

- Dark gray background, white text.
- No header navbar. Content is left-aligned.
- Monospace, modest font sizes, generous line height.
- Links are white; muted gray (`.meta`) for secondary text.

## Markup

- **No hand-written page HTML.** Pages come from `app/catalog.py` rendered
  through `app/templates/page.html`. To add a page, add an entry to the
  catalog; to change a component's markup, edit the template once.
- A page is an ordered list of panels. Panel types: `links`, `metrics`,
  `quotes`, `stories`, `chains`, `note`.
- Every data row carries the identifier that fills it — `series` (FRED),
  `symbol` (Yahoo), `derived` (computed here), `manual` (hand-entered). The
  ETL reads the same catalog, so a page and its ingest cannot drift apart.
- Prose in the catalog is trusted HTML and rendered with `|safe`. It is
  authored in this repo, never user input.
- Behavior belongs in JS files, not inline handlers. Give elements an `id` and
  wire them up externally (e.g. `#refresh`).
