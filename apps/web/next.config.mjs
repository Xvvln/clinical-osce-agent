const nextConfig = {
  experimental: {
    devtoolSegmentExplorer: false,
  },
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
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
