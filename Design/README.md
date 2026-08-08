# Hyperclients — Brand Assets

Logo direction: **AI focus brackets** — a camera-style focus frame locking onto a cyan target dot. Speaks to AI-powered search that finds and locks onto the right clients.

## Files

### Vector (`assets/`)
| File | Use |
|---|---|
| `hyperclients-logo-light.svg` | Primary lockup, light backgrounds |
| `hyperclients-logo-dark.svg` | Primary lockup, dark backgrounds (bg baked in) |
| `hyperclients-icon.svg` | Icon only, full color, transparent |
| `hyperclients-icon-mono.svg` | Single-color icon — uses `currentColor`, set via CSS `color` |
| `hyperclients-appicon.svg` | App / store icon, indigo squircle tile |

### Raster (`assets/png/`)
| File | Use |
|---|---|
| `hyperclients-icon-32.png` | Favicon |
| `hyperclients-icon-192.png` | PWA / Android icon |
| `hyperclients-icon-512.png` | PWA maskable / large |
| `apple-touch-icon-180.png` | iOS home screen |
| `hyperclients-appicon-1024.png` | App Store / Play Store |

## Colors
| Token | Hex | Role |
|---|---|---|
| Indigo | `#2A35E0` | Primary — brand, links, key UI |
| Cyan | `#13E0C2` | Accent — focus dot, highlights, success |
| Ink | `#0C1024` | Dark surfaces, headings |
| Paper | `#FFFFFF` | Light surface |

CSS custom properties are in `assets/tokens.css`.

## Typography
**Montserrat** (Google Fonts) — weights 400 / 500 / 700 / 800.
Wordmark: `Hyper` = 800 / indigo, `clients` = 500 / ink. Letter-spacing `-0.03em`.
On dark: `Hyper` = white, `clients` = cyan.

## Usage
- **Clear space:** keep padding equal to the icon's bracket gap (≈ 25% of icon height) on all sides.
- **Minimum size:** icon 16px; full lockup 120px wide.
- **Don't:** recolor outside the palette, add gradients/shadows to the mark, stretch, or rotate.
- **Mono mark:** use `hyperclients-icon-mono.svg` and set `color:` in CSS for single-color contexts (embroidery, watermark, etc).

## Favicon / web embed snippet
```html
<link rel="icon" type="image/svg+xml" href="/assets/hyperclients-icon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="/assets/png/hyperclients-icon-32.png">
<link rel="apple-touch-icon" href="/assets/png/apple-touch-icon-180.png">
```
