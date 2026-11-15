import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev:  npm run dev   (http://localhost:5173)  -> proxies the API + websocket to the FastAPI server on :8000
// Prod: npm run build -> dist/  (FastAPI serves it at "/", see ../frontend_mount.py)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
      "/api": "http://localhost:8000",
      "/demo-audio": "http://localhost:8000",
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
