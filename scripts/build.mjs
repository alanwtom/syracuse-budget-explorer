import { spawnSync } from 'node:child_process';

const result = spawnSync(process.execPath, ['node_modules/vite/bin/vite.js', 'build'], {
  stdio: 'inherit',
  env: { ...process.env, NITRO_PRESET: 'vercel' },
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
