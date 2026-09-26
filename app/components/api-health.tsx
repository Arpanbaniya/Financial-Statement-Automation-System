"use client";

import { useEffect, useState } from "react";

type HealthState = "checking" | "online" | "offline";

export function ApiHealth() {
  const [state, setState] = useState<HealthState>("checking");

  useEffect(() => {
    const controller = new AbortController();

    async function checkHealth() {
      try {
        const response = await fetch("/api/health", {
          cache: "no-store",
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error("Health check failed");
        }

        const body: unknown = await response.json();
        const isHealthy =
          typeof body === "object" &&
          body !== null &&
          "status" in body &&
          body.status === "ok";

        setState(isHealthy ? "online" : "offline");
      } catch {
        if (!controller.signal.aborted) {
          setState("offline");
        }
      }
    }

    void checkHealth();

    return () => controller.abort();
  }, []);

  const message = {
    checking: "Checking API connection",
    online: "API connection is working",
    offline: "API connection is unavailable",
  }[state];

  return (
    <p className={"api-health api-health--" + state} aria-live="polite">
      <span className="api-health__dot" aria-hidden="true" />
      {message}
    </p>
  );
}
