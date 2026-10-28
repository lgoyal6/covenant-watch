import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Nav, ThemeToggle } from "@/components/Chrome";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Covenant Watch", template: "%s · Covenant Watch" },
  description: "Loan covenant headroom for public companies, rebuilt from SEC filings with full provenance.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f6f4" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0e11" },
  ],
};

// Runs before paint so the stored or system theme never flashes.
const THEME_BOOT = `(function(){try{var p=localStorage.getItem('cw-theme');var d=p==='dark'||(p!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=d?'dark':'light';}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <header className="topbar">
          <div className="topbar-inner">
            <Link href="/" className="brand">
              <svg className="brand-mark" viewBox="0 0 20 20" aria-hidden>
                <rect x="1" y="1" width="18" height="18" rx="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <path d="M4 13.5 L8 10 L11 12 L16 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                <path d="M4 7 H16" stroke="var(--breach)" strokeWidth="1.4" strokeDasharray="2 1.6" />
              </svg>
              Covenant Watch
            </Link>
            <Nav />
            <ThemeToggle />
          </div>
        </header>
        <main>{children}</main>
        <footer className="footer">
          Covenant Watch rebuilds loan covenants from SEC EDGAR filings. Ranges reflect unmapped addbacks; refusals are shown
          rather than guessed. Not investment advice.
        </footer>
      </body>
    </html>
  );
}
