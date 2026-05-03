const adminApiUrl = process.env.CLINICAL_OSCE_ADMIN_API_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${adminApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
