import { t } from "@gold/localization";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "../components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: t("trader.appName"),
    template: `%s | ${t("trader.appName")}`,
  },
  description: t("trader.shellDescription"),
  applicationName: t("trader.appName"),
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#15130f",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
