/**
 * Demo-mode configuration. The demo company is a single constant: set NEXT_PUBLIC_DEMO_CIK
 * (or edit DEMO_CIK) once the team picks the real demo company from the eval report.
 * When unset, the demo uses the first company the API returns.
 */
export const DEMO_CIK: string | null = process.env.NEXT_PUBLIC_DEMO_CIK || null;

/** Optional: pin the covenant and quarter the demo opens (otherwise chosen from the data). */
export const DEMO_COVENANT_ID: string | null = process.env.NEXT_PUBLIC_DEMO_COVENANT || null;
export const DEMO_PERIOD_END: string | null = process.env.NEXT_PUBLIC_DEMO_PERIOD || null;
