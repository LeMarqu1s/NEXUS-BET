const path = require("path");

const empty = path.resolve(__dirname, "src/lib/empty-module.js");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  webpack: (config) => {
    const stubs = {
      "porto/internal": empty,
      porto: empty,
      "@base-org/account": empty,
      "@coinbase/wallet-sdk": empty,
      "@metamask/sdk": empty,
      "@safe-global/safe-apps-sdk": empty,
      "@safe-global/safe-apps-provider": empty,
      "@walletconnect/ethereum-provider": empty,
    };
    config.resolve.alias = { ...config.resolve.alias, ...stubs };
    config.resolve.fallback = {
      ...config.resolve.fallback,
      porto: empty,
      "porto/internal": empty,
    };
    return config;
  },
};

module.exports = nextConfig;
