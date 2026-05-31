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
};

export default nextConfig;
