import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { AccessibleRunList } from "./AccessibleRunList";
import { snapshotFixture } from "./fixtures.test-support";
import { statusLabel, phaseLabel } from "./Status";

test.each(["classic", "piqard"] as const)(
  "%s list offers every phase with state, selection and detail target",
  (strategy) => {
    const s = snapshotFixture(strategy);
    const select = vi.fn();
    render(
      <AccessibleRunList
        snapshot={s}
        selected={s.phases[0].id}
        onSelect={select}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(s.phases.length);
    for (const p of s.phases) {
      const button = screen.getByRole("button", {
        name: new RegExp("^" + phaseLabel(p.id) + " " + statusLabel(p.status)),
      });
      expect(button).toHaveAttribute("aria-controls", "selected-phase-details");
      button.focus();
      expect(button).toHaveFocus();
      fireEvent.click(button);
      expect(select).toHaveBeenLastCalledWith(p.id);
    }
    expect(
      screen.getByRole("link", { name: "Jump to phase details" }),
    ).toHaveAttribute("href", "#selected-phase-details");
  },
);

test("failed, blocked, paused, skipped and waiting states remain explicit without color", () => {
  const s = snapshotFixture();
  const statuses = ["failed", "blocked", "paused", "skipped", "waiting_human"];
  s.phases = s.phases.slice(0, 5).map((p, i) => ({
    ...p,
    status: statuses[i],
    reason: i === 0 ? "Recorded required check failed" : "",
  }));
  render(
    <AccessibleRunList
      snapshot={s}
      selected={s.phases[0].id}
      onSelect={() => {}}
    />,
  );
  for (const status of statuses)
    expect(screen.getByText(statusLabel(status))).toBeInTheDocument();
  expect(
    screen.getByText("Recorded required check failed"),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("button")[0]).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("legacy absence never creates keyboard buttons implying completed phases", () => {
  const s = snapshotFixture();
  s.phases = [];
  render(<AccessibleRunList snapshot={s} selected="" onSelect={() => {}} />);
  expect(screen.queryAllByRole("button")).toHaveLength(0);
  expect(
    screen.getByText("No strategy phases were recorded."),
  ).toBeInTheDocument();
});
