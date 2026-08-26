import vinext from "vinext";
import { defineConfig } from "vite";

// DocuFlow is a local application: the frontend is built once and served from
// disk beside a FastAPI backend on the same machine. It was scaffolded from a
// template that shipped a Cloudflare Worker entry point with D1 and R2
// bindings, none of which were ever bound to anything — 145 MB of toolchain
// installed on every machine to deploy something that cannot be deployed,
// since the backend it talks to is local by design.
export default defineConfig({
  plugins: [vinext()],
});
