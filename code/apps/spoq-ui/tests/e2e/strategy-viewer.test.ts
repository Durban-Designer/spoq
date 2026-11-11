import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { phaseLabel, statusLabel } from "../../src/Status";
import type { Snapshot } from "../../src/types";

const controlUrl = process.env.SPOQ_VIEWER_CONTROL_URL;
const realUrl = process.env.SPOQ_VIEWER_REAL_URL;
type View = {
  snapshot: Snapshot;
  review: { attempt_id: string; artifact_id: string; artifact_hash: string };
};

test("installed PIQARD viewer follows actual revisions, same-URL restart and bounded large history", async ({
  page,
}) => {
  test.skip(
    !controlUrl || !realUrl,
    "Run python3 tests/e2e/spoq_v11_viewer.py --artifact WHEEL --out RESULTS for the installed backend case",
  );
  test.setTimeout(150_000);
  const pageErrors: string[] = [];
  const externalRequests: string[] = [];
  const writes: string[] = [];
  const allowedOrigins = new Set([new URL(realUrl!).origin]);
  const timings: Record<string, number> = {};
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (!["GET", "HEAD"].includes(request.method())) writes.push(request.url());
    if (!allowedOrigins.has(new URL(request.url()).origin))
      externalRequests.push(request.url());
  });
  async function control<T = View>(action: string): Promise<T> {
    const response = await fetch(controlUrl!, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const value = await response.json();
    expect(response.ok, JSON.stringify(value)).toBe(true);
    return value as T;
  }
  async function synchronized(view: View) {
    await expect(page.getByTestId("snapshot-cursor")).toHaveText(
      String(view.snapshot.cursor),
      { timeout: 15_000 },
    );
  }
  async function graphAndListAgree(snapshot: Snapshot) {
    await page.getByRole("tab", { name: "Strategy", exact: true }).click();
    for (const phase of snapshot.phases) {
      const list = page
        .locator(".phase-sidebar button")
        .filter({ has: page.getByText(phaseLabel(phase.id), { exact: true }) });
      await expect(list).toContainText(statusLabel(phase.status));
      await expect(
        page.locator(`.react-flow__node[data-id="${phase.id}"]`),
      ).toHaveAttribute(
        "aria-label",
        `${phaseLabel(phase.id)}, ${statusLabel(phase.status)}`,
      );
    }
  }
  async function uniqueHistory(snapshot: Snapshot) {
    await page.getByRole("tab", { name: "History", exact: true }).click();
    for (const attempt of snapshot.attempts)
      await expect(
        page.locator(`[data-attempt-id="${attempt.id}"]`),
      ).toHaveCount(1);
    const visible = await page
      .locator("[data-attempt-id]")
      .evaluateAll((rows) =>
        rows.map((row) => row.getAttribute("data-attempt-id")),
      );
    expect(new Set(visible).size).toBe(visible.length);
    expect(visible.length).toBe(snapshot.attempts.length);
  }

  const initial = await control("view");
  let started = performance.now();
  await page.goto(realUrl! + "/?run=viewer");
  await synchronized(initial);
  timings.initial_render_ms = performance.now() - started;
  await expect(page.getByRole("heading", { level: 1 })).toContainText("PIQARD");
  expect(initial.snapshot.routing.reasons?.length).toBeGreaterThan(0);
  for (const reason of initial.snapshot.routing.reasons ?? [])
    await expect(
      page.getByRole("region", { name: "Why this strategy" }),
    ).toContainText(reason);
  await graphAndListAgree(initial.snapshot);

  const review = await control("to_review");
  await synchronized(review);
  await graphAndListAgree(review.snapshot);
  await expect(
    page.locator(".phase-sidebar button").filter({ hasText: "Human review" }),
  ).toContainText("Waiting for human");
  await page.getByRole("tab", { name: "Artifacts & decisions" }).click();
  await page
    .locator(".record-card")
    .filter({ hasText: review.review.artifact_id })
    .getByRole("button", { name: "View narrative plan" })
    .click();
  await expect(page.getByLabel("Escaped artifact text")).toContainText(
    "globalThis.__spoqUnsafeArtifact=true",
  );
  expect(
    JSON.parse((await page.getByLabel("Escaped artifact text").textContent())!)
      .scope,
  ).toContain('<img src=x onerror="globalThis.__spoqUnsafeArtifact=true">');
  expect(
    await page.evaluate(
      () =>
        (globalThis as { __spoqUnsafeArtifact?: boolean }).__spoqUnsafeArtifact,
    ),
  ).toBeUndefined();
  await expect(page.locator(".artifact-text img")).toHaveCount(0);

  await uniqueHistory(review.snapshot);
  await control("stop");
  await expect(
    page.getByRole("status", { name: "Viewer connection" }),
  ).toContainText("Disconnected", { timeout: 15_000 });
  await synchronized(review);
  const revised = await control("reject");
  expect(revised.review.attempt_id).not.toBe(review.review.attempt_id);
  expect(revised.review.artifact_hash).not.toBe(review.review.artifact_hash);
  started = performance.now();
  const restarted = await control<{ url: string }>("restart");
  expect(restarted.url).toBe(realUrl);
  await synchronized(revised);
  timings.reconnect_ms = performance.now() - started;
  await expect(
    page.getByRole("status", { name: "Viewer connection" }),
  ).toContainText("Connected");
  await uniqueHistory(revised.snapshot);
  await expect(
    page.locator(`[data-attempt-id="${review.review.attempt_id}"]`),
  ).toContainText("Failed");
  await expect(
    page.locator(`[data-attempt-id="${revised.review.attempt_id}"]`),
  ).toContainText("Waiting for human");
  await graphAndListAgree(revised.snapshot);
  await expect(page.locator(".rework-label").first()).toContainText(
    "Reject / rework",
  );
  await page.getByRole("tab", { name: "Artifacts & decisions" }).click();
  await expect(
    page.getByText(/Rejection · Scripted User Fixture/),
  ).toBeVisible();
  await expect(page.getByText("Historical / superseded")).toBeVisible();

  const approved = await control("approve");
  await synchronized(approved);
  await expect(
    page.getByText(/Approval · Scripted User Fixture/),
  ).toBeVisible();
  const final = await control("deliver");
  await synchronized(final);
  await expect(page.locator(".run-heading .status")).toHaveText("Passed");
  await graphAndListAgree(final.snapshot);
  await uniqueHistory(final.snapshot);
  const eventsResponse = await page.request.get(
    realUrl + "/api/runs/viewer/events?after=0&limit=100",
  );
  expect(eventsResponse.ok()).toBe(true);
  const events = await eventsResponse.json();
  expect(events.has_more).toBe(false);
  expect(events.cursor).toBe(final.snapshot.cursor);
  const eventIds = events.events.map(
    (event: { sequence: number }) => event.sequence,
  );
  expect(new Set(eventIds).size).toBe(eventIds.length);
  for (const attempt of final.snapshot.attempts)
    expect(
      events.events.some(
        (event: { payload: { attempt_id?: string } }) =>
          event.payload.attempt_id === attempt.id,
      ),
    ).toBe(true);
  await page.getByRole("tab", { name: "Work DAGs" }).click();
  await expect(
    page.getByText("Implement clamp", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("Compile and run clamp example", { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: /Inspect.*Implement clamp/ }).click();
  await expect(
    page.getByText("Clamp boundaries and invalid inputs behave correctly"),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "Strategy", exact: true }).focus();
  await page.keyboard.press("Home");
  await expect(
    page.getByRole("tab", { name: "Strategy", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Work DAGs" })).toBeFocused();
  await page.keyboard.press("End");
  await expect(
    page.getByRole("tab", { name: "History", exact: true }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: join(process.env.SPOQ_VIEWER_OUT!, "piqard-final-mobile.png"),
    fullPage: true,
  });

  const load = await control<{
    viewer_url: string;
    cursor: number;
    unique_attempts: number;
    observed_synthetic_events: number;
    history_http: { max_bytes: number };
    events_http: { max_bytes: number };
  }>("load");
  expect(load.unique_attempts).toBe(1000);
  expect(load.observed_synthetic_events).toBe(10000);
  expect(load.history_http.max_bytes).toBeLessThanOrEqual(1_000_000);
  expect(load.events_http.max_bytes).toBeLessThanOrEqual(150_000);
  allowedOrigins.add(new URL(load.viewer_url).origin);
  started = performance.now();
  await page.goto(load.viewer_url + "/?run=load-run");
  await expect(page.getByTestId("snapshot-cursor")).toHaveText(
    String(load.cursor),
  );
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(page.locator("[data-attempt-id]")).toHaveCount(100);
  timings.large_history_render_ms = performance.now() - started;
  await page.getByRole("button", { name: "Load older attempts" }).click();
  await expect(page.locator("[data-attempt-id]")).toHaveCount(200);
  const loadIds = await page
    .locator("[data-attempt-id]")
    .evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-attempt-id")),
    );
  expect(new Set(loadIds).size).toBe(200);
  expect(pageErrors).toEqual([]);
  expect(externalRequests).toEqual([]);
  expect(writes).toEqual([]);
  writeFileSync(
    join(process.env.SPOQ_VIEWER_OUT!, "browser-evidence.json"),
    JSON.stringify(
      {
        passed: true,
        browser_version: page.context().browser()?.version(),
        timings,
        final_cursor: final.snapshot.cursor,
        final_event_ids: eventIds,
        final_attempt_ids: final.snapshot.attempts.map((attempt) => attempt.id),
        historical_review_attempt: review.review.attempt_id,
        current_review_attempt: revised.review.attempt_id,
        page_errors: pageErrors,
        external_requests: externalRequests,
        browser_write_requests: writes,
        api_interception: false,
        viewport: { width: 390, height: 844 },
        artificial_read_load: load,
      },
      null,
      2,
    ),
  );
});
