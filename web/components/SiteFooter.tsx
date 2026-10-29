"use client";

import * as React from "react";
import RidgelineDitherFooter from "@/components/ui/ridgeline-dither-footer";

const REPO = "https://github.com/lgoyal6/covenant-watch";

// Neutral slate ramps matching globals.css (--bg, --text, --muted) so the footer reads as part of the app.
const LIGHT = {
  paper: "#f6f6f4",
  ink: "#16181b",
  muted: "#747a83",
  line: "#e4e5e7",
  tones: ["#f6f6f4", "#e3e5e8", "#c3c8cf", "#959ca7", "#646c78", "#3d434c", "#202429"],
};
const DARK = {
  paper: "#0c0e11",
  ink: "#e7e9ec",
  muted: "#858c96",
  line: "#1d2127",
  tones: ["#0c0e11", "#14171b", "#1c2026", "#272c34", "#373e48", "#4d5663", "#6b7584"],
};

/** The app themes with data-theme on <html> (see layout.tsx), not a .dark class, so follow that. */
function useDataTheme(): "light" | "dark" {
  const [theme, setTheme] = React.useState<"light" | "dark">("light");
  React.useEffect(() => {
    const read = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return theme;
}

function BrandMark() {
  return (
    <svg viewBox="0 0 20 20" width="22" height="22" aria-hidden="true">
      <rect x="1" y="1" width="18" height="18" rx="4" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M4 13.5 L8 10 L11 12 L16 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M4 7 H16" stroke="var(--breach)" strokeWidth="1.4" strokeDasharray="2 1.6" />
    </svg>
  );
}

export default function SiteFooter() {
  const theme = useDataTheme();
  return (
    <RidgelineDitherFooter
      name="Covenant Watch"
      brandHref="/"
      logo={<BrandMark />}
      tagline="Loan covenant headroom rebuilt from SEC filings. Ranges reflect unmapped addbacks; refusals are shown rather than guessed."
      columns={[
        { title: "Product", links: [{ label: "Companies", href: "/" }, { label: "Evaluation", href: "/eval" }, { label: "Demo", href: "/demo" }] },
        {
          title: "Data",
          links: [
            { label: "SEC EDGAR", href: "https://www.sec.gov/edgar/search/" },
            { label: "XBRL company facts", href: "https://www.sec.gov/search-filings/edgar-application-programming-interfaces" },
          ],
        },
        { title: "Project", links: [{ label: "Source code", href: REPO }, { label: "Solix AI Hackathon", badge: "2026" }] },
      ]}
      socials={[{ icon: "github", href: REPO }]}
      copyright={`© ${new Date().getFullYear()} Covenant Watch. Not investment advice.`}
      credit={{ label: "Dat & Laksh", href: REPO }}
      preset="glacier"
      palette={theme === "dark" ? DARK : LIGHT}
      seed={11}
      ridges={6}
      height="440px"
      sceneMinHeight="200px"
      maxWidth="1240px"
      fontFamily="var(--font)"
      monoFamily="var(--mono)"
    />
  );
}
