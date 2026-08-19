# SEO Audit — Chrome Extension

Manifest V3 build of the same dashboard as `../frontend-web`, talking to the
same FastAPI backend. Ships with the hosted backend as the default:

```
https://seoaudit.theonetechnologies.co.in
```

Change it any time from **Settings** inside the extension.

## Build

```bash
npm install
npm run build
```

This produces `dist/` — a static bundle plus `manifest.json`, `background.js`,
and icons copied from `public/`.

## Load into Chrome

1. Go to `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select `frontend-extension/dist`
4. Click the extension's toolbar icon — it opens the dashboard in a new tab

Re-run `npm run build` after changes and click the reload icon on the
extension card in `chrome://extensions`.

## Develop

```bash
npm run dev
```

Runs a normal Vite dev server in a browser tab. `chrome.tabs` calls (used to
prefill Current Page Check with the active tab's URL) are guarded and no-op
outside the extension, so the rest of the app works fine for iterating on UI.
To test the full extension behavior (toolbar icon, tab prefill), use the
built `dist/` folder as an unpacked extension instead.

## Backend connectivity

The manifest declares `host_permissions` for the hosted backend and for
`127.0.0.1:8000` / `localhost:8000` (local FastAPI dev). Extension pages with
a host listed in `host_permissions` bypass CORS entirely for that host, so no
backend CORS configuration is required for those origins.

If you point Settings at a different backend origin, add it to
`host_permissions` in `public/manifest.json` and rebuild — otherwise the
browser will apply normal CORS rules and the backend must allow the
extension's origin explicitly.

## Relationship to frontend-web

Same lib/ and component logic as `../frontend-web`, minus Next.js:
`next/link` → `react-router-dom` `Link`, `next/navigation` → `useNavigate` /
`useParams`, App Router pages → a single `HashRouter` (required — there's no
server to resolve `/pages`-style paths from a packaged extension). Storage
uses `localStorage` in the extension page context, same as the web app.
