const webApiUrl = process.env.CLINICAL_OSCE_WEB_API_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  experimental: {
    devtoolSegmentExplorer: false,
  },
  devIndicators: false,
  webpack(config) {
    config.watchOptions = {
      ...(config.watchOptions ?? {}),
      aggregateTimeout: 300,
      ignored: ["**/node_modules/**", "**/.next/**"],
      poll: 1000,
    };
    return config;
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${webApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
