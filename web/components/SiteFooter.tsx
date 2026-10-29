"use client";

import * as React from "react";
import RidgelineDitherFooter from "@/components/ui/ridgeline-dither-footer";

const REPO = "https://github.com/lgoyal6/covenant-watch";

// Ramps from the canvas colour (globals.css --bg) toward the periwinkle accent, so the footer reads as part of the app.
const LIGHT = {
  paper: "#f3f3f1",
  ink: "#0b0b0c",
  muted: "#76787f",
  line: "#e1e1dd",
  tones: ["#f3f3f1", "#e1e2e8", "#c2c6d6", "#959cc0", "#636ca3", "#3a4274", "#1c2140"],
};
const DARK = {
  paper: "#000000",
  ink: "#ffffff",
  muted: "#8a8a90",
  line: "#222226",
  tones: ["#000000", "#0d0e17", "#171a2e", "#232847", "#343b6b", "#4c5596", "#6d78c4"],
};

/** The app themes with data-theme on <html> (see layout.tsx), not a .dark class, so follow that. */
function useDataTheme(): "light" | "dark" {
  const [theme, setTheme] = React.useState<"light" | "dark">("dark");
  React.useEffect(() => {
    const read = () => setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return theme;
}

export default function SiteFooter() {
  const theme = useDataTheme();
  return (
    <RidgelineDitherFooter
      name="Covenant Watch"
      brandHref="/"
      logo={<></>}
      tagline="Loan covenant headroom rebuilt from SEC filings. Ranges reflect unmapped addbacks; refusals are shown rather than guessed."
      columns={[
        { title: "Product", links: [{ label: "Companies", href: "/companies" }, { label: "Evaluation", href: "/eval" }] },
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
      credit={null}
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
