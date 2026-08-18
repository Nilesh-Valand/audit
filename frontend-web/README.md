# SEO Audit — Web Frontend

Next.js (App Router) + TypeScript + Tailwind dashboard for the SEO Audit FastAPI backend.

## Setup

```bash
npm install
cp .env.example .env.local   # Windows: copy .env.example .env.local
```

Set the API base URL in `.env.local`:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Develop

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Start the FastAPI backend separately (`uvicorn` on port 8000).

## Production

```bash
npm run build
npm run start
```

| Command | Purpose |
|---------|---------|
| `npm run build` | `next build` — production compile |
| `npm run start` | `next start` — serve the build |
| `npm run lint` | ESLint |

## Deploy (Vercel)

1. Import the repo in Vercel with **Root Directory** = `frontend-web`
2. Set `NEXT_PUBLIC_API_BASE_URL` to your API origin
3. Allow that Vercel origin in backend `ALLOWED_ORIGINS`

```bash
npx vercel
```

See the [root README](../README.md) for backend setup and CORS.
