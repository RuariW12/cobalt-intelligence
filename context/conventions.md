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

- Behavior belongs in JS files, not inline handlers. Give elements an `id` and
  wire them up externally (e.g. the home page's `#refresh`).
