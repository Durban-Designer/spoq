import { test, expect } from "@playwright/test";
import { snapshotFixture } from "../../src/fixtures.test-support";

test("PIQARD revision attempts remain distinct through disconnect, duplicate/gapped events and cursor reset", async ({
  page,
}) => {
  const initial = snapshotFixture();
  let current = structuredClone(initial);
  let offline = false;
  let reset = false;
  await page.route("**/api/**", async (route) => {
    if (offline) {
      await route.abort("connectionrefused");
      return;
    }
    const url = new URL(route.request().url());
    const path = url.pathname;
    const id = decodeURIComponent(path.split("/").at(-1) ?? "");
    if (path === "/api/health") {
      await route.fulfill({ json: { project_root: "/example/project" } });
      return;
    }
    if (path === "/api/runs") {
      await route.fulfill({
        json: {
          runs: [current.run],
          pagination: { has_more: false, cursor: null },
          cursor: current.cursor,
        },
      });
      return;
    }
    if (path.endsWith("/events")) {
      const after = Number(url.searchParams.get("after") ?? 0);
      await route.fulfill({
        json: reset
          ? { events: [], cursor: 10, has_more: false, reset: true }
          : {
              events:
                after < current.cursor
                  ? [
                      {
                        sequence: current.cursor,
                        kind: "workflow.revised",
                        payload: {},
                      },
                      {
                        sequence: current.cursor,
                        kind: "workflow.revised",
                        payload: {},
                      },
                    ]
                  : [],
              cursor: current.cursor,
              has_more: false,
              reset: false,
            },
      });
      reset = false;
      return;
    }
    if (path.includes("/attempts/")) {
      await route.fulfill({ json: current.attempts.find((a) => a.id === id) });
      return;
    }
    if (path.includes("/artifacts/")) {
      await route.fulfill({
        json: {
          ...current.artifacts.find((a) => a.id === id),
          content: "Revised narrative",
          render_as: "text",
        },
      });
      return;
    }
    await route.fulfill({ json: current });
  });
  await page.goto("/?run=" + initial.run.run_id);
  await expect(page.getByTestId("snapshot-cursor")).toHaveText("42");
  const narrative = page
    .locator(".phase-sidebar button")
    .filter({ has: page.getByText("Narrative plan", { exact: true }) });
  await narrative.click();
  await expect(narrative).toBeFocused();
  const viewport = await page
    .locator(".react-flow__viewport")
    .first()
    .getAttribute("style");
  offline = true;
  await expect(
    page.getByRole("status", { name: "Viewer connection" }),
  ).toContainText("Disconnected");
  await expect(page.getByTestId("snapshot-cursor")).toHaveText("42");
  current.cursor = 70;
  current.run.revision = 8;
  current.attempts.find((a) => a.id === "attempt-review")!.status = "failed";
  current.attempts.push(
    {
      id: "narrative-2",
      phase_id: "narrative",
      number: 2,
      status: "passed",
      owner: "fixture-worker",
      evidence: { provenance: "scripted adapter" },
    },
    {
      id: "review-2",
      phase_id: "review",
      number: 2,
      status: "waiting_human",
      owner: "fixture-worker",
      evidence: {},
    },
  );
  Object.assign(
    current.phases.find((p) => p.id === "narrative")!,
    { attempt_id: "narrative-2", number: 2 },
  );
  Object.assign(
    current.phases.find((p) => p.id === "review")!,
    { attempt_id: "review-2", number: 2 },
  );
  current.decisions.push({
    id: "rejection-first",
    attempt_id: "attempt-review",
    artifact_id: "narrative-artifact",
    artifact_hash: "c".repeat(64),
    source: "user",
    author: "Scripted human fixture",
    decision: "reject",
    reason: "Clarify acceptance before decomposition",
    specification_hash: "b".repeat(64),
    definition_hash: "a".repeat(64),
  });
  offline = false;
  await expect(page.getByTestId("snapshot-cursor")).toHaveText("70");
  await expect(
    page.getByRole("status", { name: "Viewer connection" }),
  ).toContainText("Connected");
  await expect(narrative).toBeFocused();
  expect(
    await page.locator(".react-flow__viewport").first().getAttribute("style"),
  ).toBe(viewport);
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(
    page.locator('[data-attempt-id="attempt-review"]'),
  ).toContainText("Failed");
  await expect(page.locator('[data-attempt-id="review-2"]')).toContainText(
    "Waiting for human",
  );
  expect(await page.locator('[data-attempt-id="narrative-2"]').count()).toBe(1);
  expect(
    await page.locator('[data-attempt-id="attempt-narrative"]').count(),
  ).toBe(1);
  await page.getByRole("tab", { name: "Artifacts & decisions" }).click();
  await expect(page.getByText("Historical / superseded")).toBeVisible();
  current = structuredClone(initial);
  current.cursor = 10;
  reset = true;
  await expect(page.getByTestId("snapshot-cursor")).toHaveText("10");
  await expect(page.getByText(/Event cursor reset/)).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "Artifacts & decisions" }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "History", exact: true }).click();
  await expect(page.locator('[data-attempt-id="review-2"]')).toHaveCount(0);
});
