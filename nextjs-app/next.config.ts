import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Disable x-powered-by header
  poweredByHeader: false,
  // Allow the OpenCode proxy to stream responses
  experimental: {
    serverActions: {
      allowedOrigins: ["localhost:3000"],
    },
  },
};

export default nextConfig;
