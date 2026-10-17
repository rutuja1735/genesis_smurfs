const backend = (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

export default {
  async rewrites() {
    return { fallback: [
      { source: '/api/:path*', destination: `${backend}/api/:path*` },
      { source: '/docs', destination: `${backend}/docs` },
      { source: '/openapi.json', destination: `${backend}/openapi.json` },
    ] };
  },
};
