/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output: Next.js bundles only the needed node_modules into a
  // minimal `.next/standalone` dir, runnable with `node server.js`. Lets the
  // production image skip a full node_modules copy.
  output: "standalone",
  // Proxy /api/* to the backend service inside the cluster.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
      {
        // CopilotKit AG-UI endpoint lives at the backend root (/).
        source: "/copilotkit/:path*",
        destination: `${backend}/copilotkit/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
