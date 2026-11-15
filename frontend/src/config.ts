// Same-origin by default (FastAPI serves this app). To host the frontend elsewhere (Vercel/Netlify), set
// VITE_BACKEND_URL=https://your-backend.example.com at build time and CORS_ORIGINS=<frontend origin> on the server.
const raw = ((import.meta.env.VITE_BACKEND_URL as string | undefined) ?? "").replace(/\/$/, "");

export const HTTP_BASE = raw;

export function wsUrl(): string {
  if (raw) return raw.replace(/^http/, "ws") + "/ws";
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}
