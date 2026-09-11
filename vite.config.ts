import tailwindcss from '@tailwindcss/postcss';
import { nitro } from 'nitro/vite';
import vinext from 'vinext';
import { defineConfig } from 'vite';
export default defineConfig(({ command, isPreview }) => ({
  css: { postcss: { plugins: [tailwindcss()] } },
  // Vinext owns local serving; Nitro packages the deployment build.
  plugins: [vinext(), ...(!process.env.SITES_BUILD && (command === 'build' || isPreview) ? [nitro()] : [])],
}));
