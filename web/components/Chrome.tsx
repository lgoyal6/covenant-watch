"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type Pref = "system" | "light" | "dark";

function apply(pref: Pref) {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function ThemeToggle() {
  const [pref, setPref] = useState<Pref>("system");

  useEffect(() => {
    let stored: Pref = "system";
    try {
      const v = localStorage.getItem("cw-theme");
      if (v === "light" || v === "dark") stored = v;
    } catch {}
    setPref(stored);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      let cur: Pref = "system";
      try {
        const v = localStorage.getItem("cw-theme");
        if (v === "light" || v === "dark") cur = v;
      } catch {}
      apply(cur);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const next: Record<Pref, Pref> = { system: "light", light: "dark", dark: "system" };
  const label: Record<Pref, string> = { system: "Auto", light: "Light", dark: "Dark" };

  return (
    <button
      type="button"
      className="icon-btn"
      title={`Theme: ${label[pref]} (click for ${label[next[pref]]})`}
      aria-label={`Theme: ${label[pref]}. Switch to ${label[next[pref]]}.`}
      onClick={() => {
        const n = next[pref];
        setPref(n);
        try {
          if (n === "system") localStorage.removeItem("cw-theme");
          else localStorage.setItem("cw-theme", n);
        } catch {}
        apply(n);
      }}
    >
      <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
        <circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 1.8a6.2 6.2 0 0 1 0 12.4z" fill="currentColor" />
      </svg>
      {label[pref]}
    </button>
  );
}

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/", label: "Companies" },
  { href: "/eval", label: "Evaluation" },
  { href: "/demo", label: "Demo" },
];

export function Nav() {
  const path = usePathname() || "/";
  return (
    <nav className="nav" aria-label="Main">
      {LINKS.map((l) => {
        const active = l.href === "/" ? path === "/" || path.startsWith("/company") : path.startsWith(l.href);
        return (
          <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined}>
            {l.label}
          </Link>
        );
      })}
    </nav>
  );
}
