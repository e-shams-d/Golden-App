import { t } from "@gold/localization";
import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: t("trader.appName"),
    short_name: "سامانه طلا",
    description: t("trader.shellDescription"),
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f6f4ef",
    theme_color: "#15130f",
    lang: "fa",
    dir: "rtl",
    icons: [
      {
        src: "/icons/app-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "any",
      },
      {
        src: "/icons/app-icon.svg",
        sizes: "any",
        type: "image/svg+xml",
        purpose: "maskable",
      },
    ],
  };
}
