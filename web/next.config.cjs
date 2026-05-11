/**
 * Next.js config — sets up bundling for Web Workers and WebAssembly.
 *
 * Required by @mlc-ai/web-llm:
 * - Workers loaded via `new Worker(new URL(...))` need webpack 5 worker support.
 * - WebGPU shaders rely on async WebAssembly.
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.experiments = {
        ...config.experiments,
        asyncWebAssembly: true,
        topLevelAwait: true,
      };
    }
    // Don't try to bundle WebLLM into server-side code.
    config.resolve.alias = {
      ...config.resolve.alias,
    };
    return config;
  },
  // WebLLM is browser-only; never resolve it during SSR.
  serverExternalPackages: ["@mlc-ai/web-llm"],
};

module.exports = nextConfig;
