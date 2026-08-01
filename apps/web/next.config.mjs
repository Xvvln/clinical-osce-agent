const nextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: "base-uri 'self'; frame-ancestors 'none'; object-src 'none'; form-action 'self'",
          },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), geolocation=(), microphone=(self), payment=(), usb=()",
          },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
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
