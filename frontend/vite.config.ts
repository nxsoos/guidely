import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.GUIDELY_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": target,
      "/health": target,
      "/metrics": target,
    },
  },
  preview: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
    },
  },
});
