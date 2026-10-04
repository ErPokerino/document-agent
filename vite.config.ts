import vinext from "vinext";
import { defineConfig } from "vite";

// The frontend is built once and served by `vinext start` beside the FastAPI
// backend — on a developer machine, or in the container in deploy/. It was
// scaffolded from a template that shipped a Cloudflare Worker entry point with
// D1 and R2 bindings, never bound to anything; that apparatus and its 145 MB of
// toolchain were removed. Deployment stays provider-neutral (docs/deployment.md).
export default defineConfig({
  plugins: [vinext()],
});
