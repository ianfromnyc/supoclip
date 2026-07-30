import { describe, expect, it } from "vitest";

import { computeTrustedOrigins } from "./trusted-origins";

describe("computeTrustedOrigins", () => {
  it("includes the local development origins outside production", () => {
    const origins = computeTrustedOrigins({ NODE_ENV: "development" });

    expect(origins).toEqual([
      "http://localhost:3001",
      "http://127.0.0.1:3001",
      "http://localhost:3107",
      "http://sp.localhost:3107",
      "http://supoclip.localhost:3107",
    ]);
  });

  it("omits the development origins in production", () => {
    const origins = computeTrustedOrigins({ NODE_ENV: "production" });

    expect(origins).toEqual([]);
  });

  it("trusts the loopback twin of a localhost origin in production", () => {
    // Stock `docker-compose up` is a production build that only sets these two
    // variables to the localhost form, but the port is published on 127.0.0.1,
    // so a user may browse to either host.
    const origins = computeTrustedOrigins({
      NODE_ENV: "production",
      NEXT_PUBLIC_APP_URL: "http://localhost:3001",
      BETTER_AUTH_URL: "http://localhost:3001",
    });

    expect(origins).toEqual(["http://localhost:3001", "http://127.0.0.1:3001"]);
  });

  it("trusts only the deployed origin for a public domain in production", () => {
    const origins = computeTrustedOrigins({
      NODE_ENV: "production",
      NEXT_PUBLIC_APP_URL: "https://app.example.com",
      BETTER_AUTH_URL: "https://app.example.com",
    });

    expect(origins).toEqual(["https://app.example.com"]);
  });

  it("dedupes origins that the env values and dev list both produce", () => {
    // The two variables here are loopback twins of each other, so between them
    // they generate the same pair twice, and the dev list repeats it again.
    const origins = computeTrustedOrigins({
      NODE_ENV: "development",
      NEXT_PUBLIC_APP_URL: "http://localhost:3001",
      BETTER_AUTH_URL: "http://127.0.0.1:3001",
    });

    expect(origins).toEqual([
      "http://localhost:3001",
      "http://127.0.0.1:3001",
      "http://localhost:3107",
      "http://sp.localhost:3107",
      "http://supoclip.localhost:3107",
    ]);
  });

  it("ignores values that are not parseable URLs", () => {
    const origins = computeTrustedOrigins({
      NODE_ENV: "production",
      NEXT_PUBLIC_APP_URL: "not-a-url",
      BETTER_AUTH_URL: "https://app.example.com",
    });

    expect(origins).toEqual(["https://app.example.com"]);
  });
});
