import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Nav } from "@/components/Chrome";
import SiteFooter from "@/components/SiteFooter";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Covenant Watch", template: "%s · Covenant Watch" },
  description: "Loan covenant headroom for public companies, rebuilt from SEC filings with full provenance.",
};

export const viewport: Viewport = {
  themeColor: "#000000",
};

// One theme: the dark bento canvas the dashboard and footer are drawn on. Set before paint so nothing flashes light.
const THEME_BOOT = `document.documentElement.dataset.theme='dark';`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <Link href="/" className="brand">
              <span className="brand-text">Covenant Watch</span>
            </Link>
            <Nav />
          </div>
        </header>
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
