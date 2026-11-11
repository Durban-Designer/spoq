import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";
import { snapshotFixture } from "../../src/fixtures.test-support";
for (const strategy of ["classic", "piqard"] as const) {
  for (const failure of [false, true]) {
    test(`${strategy} ${failure ? "failure" : "active"} supports keyboard, narrow layout and accessible views`, async ({
      page,
    }) => {
      const snapshot = snapshotFixture(strategy);
      if (failure) {
        snapshot.run.status = "failed";
        const current = snapshot.phases.find((p) =>
          ["running", "waiting_human"].includes(p.status),
        )!;
        current.status = "failed";
        current.reason = "Required scripted fixture check failed";
        snapshot.attempts.find((a) => a.id === current.attempt_id)!.status =
          "failed";
        snapshot.blockers = ["Required scripted fixture check failed"];
      }
      await page.route("**/api/**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        const id = decodeURIComponent(path.split("/").at(-1) ?? "");
        const data =
          path === "/api/health"
            ? { project_root: "/example/very-long-local-project-path" }
            : path === "/api/runs"
              ? {
                  runs: [snapshot.run],
                  pagination: { has_more: false, cursor: null },
                  cursor: snapshot.cursor,
                }
              : path.endsWith("/events")
                ? {
                    events: [],
                    cursor: snapshot.cursor,
                    has_more: false,
                    reset: false,
                  }
                : path.includes("/attempts/")
                  ? snapshot.attempts.find((a) => a.id === id)
                  : path.includes("/artifacts/")
                    ? {
                        ...snapshot.artifacts.find((a) => a.id === id),
                        content: "Escaped narrative content",
                        render_as: "text",
                      }
                    : snapshot;
        await route.fulfill({ json: data });
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/?run=" + snapshot.run.run_id);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const last = page.locator(".phase-sidebar button").last();
      await last.focus();
      await page.keyboard.press("Enter");
      await expect(last).toHaveAttribute("aria-pressed", "true");
      await page.keyboard.press("Tab");
      await expect(
        page.getByRole("link", { name: "Jump to phase details" }),
      ).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(
        page.getByRole("complementary", { name: "Phase details" }),
      ).toBeFocused();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await page.getByRole("tab", { name: "Strategy", exact: true }).focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("tab", { name: "Work DAGs" })).toBeFocused();
      await expect(
        page.getByRole("tab", { name: "Work DAGs" }),
      ).toHaveAttribute("aria-selected", "true");
      await page.keyboard.press("End");
      await expect(
        page.getByRole("tab", { name: "History", exact: true }),
      ).toBeFocused();
      for (const name of ["History", "Artifacts & decisions", "Strategy"]) {
        await page.getByRole("tab", { name, exact: true }).click();
        await expect(
          page.getByRole("tab", { name, exact: true }),
        ).toHaveAttribute("aria-selected", "true");
        const results = await new AxeBuilder({ page }).analyze();
        expect(results.violations).toEqual([]);
      }
      const fit = page.getByRole("button", {
        name: "Fit strategy graph",
        exact: true,
      });
      await fit.scrollIntoViewIfNeeded();
      const button = await fit.boundingBox();
      const graph = await page
        .getByRole("region", { name: "Read-only strategy graph" })
        .boundingBox();
      expect(button!.y).toBeGreaterThanOrEqual(graph!.y);
      expect(button!.y + button!.height).toBeLessThan(
        graph!.y + graph!.height - 20,
      );
      await fit.click();
      await page.screenshot({
        path: `test-results/${strategy}-${failure ? "failure" : "active"}-mobile.png`,
        fullPage: true,
      });
    });
  }
}
