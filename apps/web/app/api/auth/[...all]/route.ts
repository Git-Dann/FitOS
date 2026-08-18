/**
 * Better Auth's HTTP surface, including the JWKS the API verifies against.
 *
 * Everything under /api/auth is Better Auth's; nothing else in the web app
 * issues or inspects tokens.
 *
 * `force-dynamic` because none of this is prerenderable: every response depends
 * on cookies, and a cached auth response is a security bug rather than a
 * performance win.
 */
import { getAuth } from "@/lib/auth";

export const dynamic = "force-dynamic";

export const GET = (request: Request) => getAuth().handler(request);
export const POST = (request: Request) => getAuth().handler(request);
