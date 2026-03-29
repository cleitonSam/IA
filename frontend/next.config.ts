import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // API_URL = URL interna do backend (usado no EasyPanel ou dev local sem nginx)
    // Se não definida, o nginx já faz o roteamento (docker-compose com nginx)
    const apiUrl = process.env.API_URL;
    if (!apiUrl) return [];

    return [
      {
        source: "/api-backend/:path*",
        destination: `${apiUrl}/:path*`,
      },
      // Proxy para webhooks do UazAPI — permite usar o domínio do frontend como webhook URL
      {
        source: "/uazapi/:path*",
        destination: `${apiUrl}/uazapi/:path*`,
      },
      // Proxy para webhooks do Chatwoot
      {
        source: "/webhooks/:path*",
        destination: `${apiUrl}/webhooks/:path*`,
      },
    ];
  },
};

export default nextConfig;
