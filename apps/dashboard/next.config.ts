import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      phaser: "phaser/dist/phaser.js",
    };
    return config;
  },
};

export default nextConfig;
