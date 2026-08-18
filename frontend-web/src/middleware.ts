import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Access rules mirrored from the Chrome extension:
 * - No user login / auth token / session cookie exists
 * - Every dashboard route is reachable without credentials
 * - chrome.storage held prefs only (API URL, selected audit) — not auth
 *
 * Therefore middleware does not gate routes. When FastAPI auth is added,
 * check an httpOnly session cookie here and redirect unauthenticated users
 * away from protected matchers.
 */
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Run on app routes so future auth checks have a single entry point.
     * Skip Next internals and static assets.
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
