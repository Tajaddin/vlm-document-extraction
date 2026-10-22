// Bundle each handler with its AWS SDK clients into dist/<name>/index.mjs (Terraform zips the folder).
// The SDK is bundled, not taken from the runtime, so the version that was tested is the version that runs.
import { build } from "esbuild";

for (const name of ["submit", "status"]) {
  await build({
    entryPoints: [`src/${name}.ts`],
    outfile: `dist/${name}/index.mjs`,
    bundle: true,
    platform: "node",
    target: "node22",
    format: "esm",
    minify: true,
    sourcemap: false,
    legalComments: "none",
    // a CommonJS dependency inside an ES module bundle needs `require`
    banner: { js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);" },
  });
  console.log(`built dist/${name}/index.mjs`);
}
