import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";
import { snapshotFixture } from "../../src/fixtures.test-support";
for (const strategy of ["classic", "piqard"] as const) {
  test(`${strategy} shows the committed strategy graph and status without write requests`, async ({
    page,
  }) => {
    const snapshot = snapshotFixture(strategy);
    const writes: string[] = [];
    const remote: string[] = [];
    page.on("request", (r) => {
      if (r.method() !== "GET") writes.push(r.method());
      if (!r.url().startsWith("http://127.0.0.1:4173")) remote.push(r.url());
    });
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/events")) {
        await route.fulfill({
          json: {
            events: [],
            cursor: snapshot.cursor,
            has_more: false,
            reset: false,
          },
        });
        return;
      }
      const id = decodeURIComponent(path.split("/").at(-1) ?? "");
      if (path.includes("/attempts/")) {
        await route.fulfill({
          json: snapshot.attempts.find((a) => a.id === id),
        });
        return;
      }
      if (path.includes("/artifacts/")) {
        await route.fulfill({
          json: {
            ...snapshot.artifacts.find((a) => a.id === id),
            content: "## Scope\nFixture narrative",
            render_as: "text",
          },
        });
        return;
      }
      if (path.includes("/nodes/")) {
        await route.fulfill({
          json: {
            ...snapshot.work.nodes.find((n) => n.id === id),
            data: { acceptance_criteria: ["Recorded criterion"] },
          },
        });
        return;
      }
      await route.fulfill({
        json:
          path === "/api/health"
            ? { project_root: "/example/project" }
            : path === "/api/runs"
              ? {
                  runs: [snapshot.run],
                  pagination: { has_more: false, cursor: null },
                  cursor: 42,
                }
              : snapshot,
      });
    });
    await page.goto("/?run=" + snapshot.run.run_id);
    await expect(
      page.getByRole("heading", {
        name: snapshot.definition.title,
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Read-only strategy graph" }),
    ).toBeVisible();
    const active = strategy === "piqard" ? "Human review" : "Execute tasks";
    await expect(
      page.locator(".react-flow__node").filter({ hasText: active }),
    ).toBeVisible();
    await expect(
      page.getByRole("status", { name: "Viewer connection" }),
    ).toContainText("Connected");
    const alternative = strategy === "piqard" ? "Narrative plan" : "Plan";
    await page
      .locator(".phase-sidebar button")
      .filter({ has: page.getByText(alternative, { exact: true }) })
      .click();
    await expect(page.locator(".detail-panel h2")).toHaveText(alternative);
    await page
      .locator(".phase-sidebar button")
      .filter({ hasText: active })
      .click();
    await expect(page.locator(".detail-panel h2")).toHaveText(active);
    await expect(
      page.getByRole("button", { name: "Fit strategy graph", exact: true }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Work DAGs" }).click();
    await page
      .getByRole("button", { name: "Open API Task DAG", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Inspect API tests", exact: true })
      .click();
    await expect(
      page.getByRole("region", { name: "Work acceptance details" }),
    ).toContainText("Recorded criterion");
    await page.getByRole("tab", { name: "Artifacts & decisions" }).click();
    await page
      .getByRole("button", { name: "View narrative plan", exact: true })
      .click();
    await expect(page.getByLabel("Escaped artifact text")).toContainText(
      "Fixture narrative",
    );
    await page.getByRole("tab", { name: "Strategy", exact: true }).click();
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    expect(writes).toEqual([]);
    expect(remote).toEqual([]);
    await page.screenshot({
      path: `test-results/${strategy}-graph.png`,
      fullPage: true,
    });
  });
}
