"use client";

import Link from "next/link";
import RidgelineDitherFooter from "@/components/ui/ridgeline-dither-footer";

const REPO = "https://github.com/lgoyal6/covenant-watch";

// Same canvas-to-periwinkle ramp as the site footer, so entering the app feels continuous.
const PALETTE = {
  paper: "#000000",
  ink: "#ffffff",
  muted: "#8a8a90",
  line: "#222226",
  tones: ["#000000", "#0d0e17", "#171a2e", "#232847", "#343b6b", "#4c5596", "#6d78c4"],
};

/** Front page: the dithered range full screen, the pitch, and one way in. */
export default function Landing() {
  return (
    <div className="landing">
      <style>{CSS}</style>
      <RidgelineDitherFooter
        name="Covenant Watch"
        brandHref="/"
        logo={<></>}
        tagline="Covenant breaches are the first domino of default. We rebuild every loan covenant from the contract and the company's own SEC filings, and show how much room is left each quarter, with every number cited."
        columns={[{ title: "Explore", links: [{ label: "Dashboard", href: "/dashboard" }, { label: "Companies", href: "/companies" }, { label: "Evaluation", href: "/eval" }] }]}
        socials={[{ icon: "github", href: REPO }]}
        copyright="Built from public SEC EDGAR filings. Not investment advice."
        credit={null}
        preset="night"
        palette={PALETTE}
        seed={11}
        ridges={7}
        height="100svh"
        sceneMinHeight="46svh"
        maxWidth="1240px"
        fontFamily="var(--font)"
        monoFamily="var(--mono)"
      />
      <Link href="/dashboard" className="enter">
        Enter <span aria-hidden="true">→</span>
      </Link>
    </div>
  );
}

const CSS = `
.landing { position: relative; min-height: 100svh; background: #000; }
.landing .rdf-logo { font-size: clamp(44px, 7vw, 88px); font-weight: 700; letter-spacing: -0.05em; }
.landing .rdf-tag { max-width: 46ch; font-size: clamp(14px, 1.3vw, 17px); line-height: 1.55; color: rgba(255,255,255,.62); }
.landing .rdf-brand { gap: 26px; }
.landing .enter {
  position: absolute; left: 50%; bottom: 17svh; transform: translateX(-50%); z-index: 5;
  display: inline-flex; align-items: center; gap: 10px; height: 52px; padding: 0 26px; border-radius: 26px;
  background: #fff; color: #0b0b0c; font: 600 16px var(--font); letter-spacing: -0.01em; text-decoration: none;
  box-shadow: 0 18px 50px -12px rgba(109, 120, 196, .65);
  animation: enter-in 1s cubic-bezier(.2,.7,.1,1) 1.6s both; transition: transform .35s cubic-bezier(.2,.7,.1,1), box-shadow .35s;
}
.landing .enter:hover { text-decoration: none; transform: translateX(-50%) translateY(-2px); box-shadow: 0 24px 60px -12px rgba(109, 120, 196, .9); }
.landing .enter span { transition: transform .35s cubic-bezier(.2,.7,.1,1); }
.landing .enter:hover span { transform: translateX(4px); }
@keyframes enter-in { from { opacity: 0; transform: translateX(-50%) translateY(14px); } }
@media (prefers-reduced-motion: reduce) { .landing .enter { animation: none; } }
`;
