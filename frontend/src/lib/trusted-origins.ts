/**
 * Local origins that are only trusted outside production builds. Local
 * `next dev` serves the app on 3107, and the `sp.`/`supoclip.` subdomains are
 * convenience hostnames some contributors point at localhost.
 */
const DEVELOPMENT_ORIGINS = [
  "http://localhost:3001",
  "http://127.0.0.1:3001",
  "http://localhost:3107",
  "http://sp.localhost:3107",
  "http://supoclip.localhost:3107",
];

/** The two hostnames that mean "this machine", keyed by their counterpart. */
const LOOPBACK_TWINS: Record<string, string> = {
  localhost: "127.0.0.1",
  "127.0.0.1": "localhost",
};

type TrustedOriginEnv = {
  NEXT_PUBLIC_APP_URL?: string;
  BETTER_AUTH_URL?: string;
  NODE_ENV?: string;
};

/** Reduces a configured URL to its bare origin, ignoring unparseable values. */
function toOrigin(value?: string): string | null {
  if (!value) {
    return null;
  }

  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

/**
 * For a loopback origin, returns the same origin reached via the other
 * loopback hostname (localhost <-> 127.0.0.1), keeping protocol and port.
 * Returns null for any non-loopback host, so public domains are unaffected.
 */
function toLoopbackTwin(origin: string): string | null {
  try {
    const url = new URL(origin);
    const twin = LOOPBACK_TWINS[url.hostname];

    if (!twin) {
      return null;
    }

    url.hostname = twin;
    return url.origin;
  } catch {
    return null;
  }
}

/**
 * Builds the list of origins Better Auth will accept requests from.
 *
 * Origins derived from the configured URLs are always trusted. Each loopback
 * origin also contributes its twin, because browsers treat localhost and
 * 127.0.0.1 as separate origins and stock Docker publishes the port on the
 * latter while only configuring the former. The hardcoded development origins
 * are added outside production so they never widen a real deployment.
 */
export function computeTrustedOrigins(env: TrustedOriginEnv): string[] {
  const configured = [
    toOrigin(env.NEXT_PUBLIC_APP_URL),
    toOrigin(env.BETTER_AUTH_URL),
  ].filter((origin): origin is string => Boolean(origin));

  const origins = configured.flatMap((origin) => {
    const twin = toLoopbackTwin(origin);
    return twin ? [origin, twin] : [origin];
  });

  if (env.NODE_ENV !== "production") {
    origins.push(...DEVELOPMENT_ORIGINS);
  }

  return Array.from(new Set(origins));
}
