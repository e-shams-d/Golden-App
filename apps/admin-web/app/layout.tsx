import { t } from "@gold/localization";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers } from "../components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: t("admin.appName"),
    template: `%s | ${t("admin.appName")}`,
  },
  description: t("admin.shellDescription"),
  applicationName: t("admin.appName"),
  robots: { index: false, follow: false },
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
