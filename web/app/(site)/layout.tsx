import Link from "next/link";
import { Nav } from "@/components/Chrome";
import SiteFooter from "@/components/SiteFooter";
import AnalystPanel from "@/components/agents/AnalystPanel";

/** The app: top bar, page, footer. The landing page (app/page.tsx) sits outside this group. */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
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
      <AnalystPanel />
    </>
  );
}
