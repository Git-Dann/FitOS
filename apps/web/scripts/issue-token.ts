/**
 * Mint one real token and print it with the JWKS that verifies it.
 *
 * This exists so the JWKS contract can be tested across the runtime boundary
 * rather than asserted on each side separately. ADR 0005 puts a Node process
 * and a Python process in the authentication path; a mock on either side proves
 * only that the mock agrees with itself.
 *
 * Output is one line of JSON on stdout: { token, jwks, userId, email }.
 * Everything else goes to stderr so the caller can parse stdout directly.
 *
 * Called by services/api/tests/test_jwks_contract.py. Not part of the running
 * application, and not reachable from it.
 */
import { auth } from "../lib/auth";

async function main(): Promise<void> {
  const email = `contract-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@example.com`;

  const signUp = await auth.api.signUpEmail({
    body: { email, password: "correct-horse-battery-staple", name: "Contract Probe" },
    returnHeaders: true,
  });

  const cookie = (signUp.headers ?? new Headers()).getSetCookie?.().join("; ") ?? "";
  const { token } = await auth.api.getToken({ headers: new Headers({ cookie }) });
  const jwks = await auth.api.getJwks();

  process.stdout.write(
    JSON.stringify({ token, jwks, userId: signUp.response?.user?.id ?? null, email }),
  );
}

// Wrapped rather than top-level await: tsx loads this through a CommonJS
// transform, which refuses a module that awaits at the top level. The catch is
// what turns a failure into a non-zero exit, which is how the caller notices.
main().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
