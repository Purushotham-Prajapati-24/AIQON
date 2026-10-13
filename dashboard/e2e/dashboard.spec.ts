import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const SECTIONS = ["fleet", "shipment", "fix", "alerts", "proof"] as const;

/** Scroll through every section so lazy chunks, data and reveal animations all settle. */
async function visitAllSections(page: Page) {
  for (const id of SECTIONS) {
    await page.locator(`#${id}`).first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(500);
  }
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1200); // counters and fades finish (≈1.1 s)
}

/** Text as assistive tech gets it: animated (aria-hidden) digits removed. */
async function accessibleText(page: Page, selector: string) {
  return page.$$eval(selector, (els) =>
    els.map((e) => {
      const c = e.cloneNode(true) as HTMLElement;
      c.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
      return (c.textContent ?? "").replace(/\s+/g, " ").trim();
    }),
  );
}

function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/ERR_CONNECTION_REFUSED|Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

/** The demo reviewer, signed in to the offline preview (what Login stores when no API answers). */
const REVIEWER = { id: "reviewer", name: "Aiqon Reviewer", role: "first", title: "Assessment reviewer", team: "Aiqon" };

// Every test except the sign-in ones starts already signed in as the reviewer ("First look" view).
test.beforeEach(async ({ page }, info) => {
  if (info.title.includes("sign-in")) return;
  await page.addInitScript((user) => {
    const expiresAt = Math.floor(Date.now() / 1000) + 3600;
    sessionStorage.setItem("cascade-offline-session", JSON.stringify({ user, expiresAt, kind: "offline" }));
  }, REVIEWER);
});

test.describe("sign-in", () => {
  test("sign-in offers four demo accounts; one key opens that person's section; sign-out returns", async ({ page }) => {
    await page.goto("/?source=snapshot");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/sign in/i);
    const accounts = page.getByRole("list", { name: "Demo accounts" }).getByRole("button");
    await expect(accounts).toHaveCount(4);
    await page.keyboard.press("2"); // Marco Bianchi, customer support -> opens on 02 Shipment
    const signOut = page.getByRole("button", { name: /sign out marco bianchi/i });
    await expect(signOut).toBeVisible();
    await expect(page.locator("#shipment")).toBeInViewport({ ratio: 0.05, timeout: 15_000 });

    await signOut.click();
    await expect(page.getByRole("list", { name: "Demo accounts" })).toBeVisible();
    expect(await page.evaluate(() => sessionStorage.getItem("cascade-offline-session"))).toBeNull();
  });

  test("sign-in form rejects a wrong password with an announced error", async ({ page }) => {
    await page.goto("/?source=snapshot");
    await page.getByLabel(/username/i).fill("priya");
    await page.getByLabel(/^password$/i).fill("not-the-password");
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await expect(page.getByRole("alert")).toContainText(/don't match/i);
    await expect(page.getByLabel(/^password$/i)).toHaveAttribute("aria-invalid", "true");
  });

  test("sign-in screen has no serious or critical accessibility violations", async ({ page }) => {
    await page.goto("/?source=snapshot");
    await expect(page.getByRole("list", { name: "Demo accounts" }).getByRole("button")).toHaveCount(4);
    await page.waitForTimeout(1500);
    const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking.flatMap((v) => v.nodes.slice(0, 4).map((n) => `${v.id} ${n.target.join(" ")}`))).toEqual([]);
  });
});

test.describe("recorded run", () => {
  test("renders every section with real numbers and no errors", async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto("/?source=snapshot");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(/late at the hub/i);
    await expect(page.getByRole("status").filter({ hasText: "Recorded run" }).first()).toBeVisible();
    await visitAllSections(page);

    for (const id of SECTIONS) await expect(page.locator(`section#${id}`)).toBeVisible();
    await expect(page.locator('section[aria-label$="(unavailable)"]')).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);

    // Headings expose real numbers to assistive tech — never "0 of 0" placeholders.
    const h2 = (await accessibleText(page, "h2")).join(" | ");
    expect(h2).toMatch(/[1-9]\d*\s+of\s+[1-9]\d*\s+shipments/i);
    expect(h2).not.toMatch(/\b0\s+of\s+0\b/i);

    // ...and the visible count-up lands on the same value.
    const fleetCount = page.locator("#fleet h2 .text-late").first();
    await fleetCount.scrollIntoViewIfNeeded(); // counters animate while visible, by design
    const target = (await fleetCount.locator(".sr-only").textContent())?.trim();
    await expect.poll(async () => (await fleetCount.locator('[aria-hidden="true"]').textContent())?.trim()).toBe(target);
    expect(errors).toEqual([]);
  });

  test("hero replay is keyboard operable (arrows, Home, End move selection and focus)", async ({ page }) => {
    await page.goto("/?source=snapshot");
    const tabs = page.getByRole("tablist", { name: "Replay milestones" }).getByRole("tab");
    await expect(tabs.first()).toBeVisible();
    const n = await tabs.count();
    await tabs.nth(1).click();
    await page.keyboard.press("Home");
    await expect(tabs.first()).toBeFocused();
    await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("End");
    await expect(tabs.nth(n - 1)).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(tabs.nth(n - 2)).toHaveAttribute("aria-selected", "true");
  });
});

test("falls back to the recording when the live API stops answering", async ({ page }) => {
  // The probe and the session check succeed (API "up", user signed in), then every data call
  // fails: an outage mid-session. Later routes take precedence, so the catch-all goes first.
  await page.route("**/api/v1/**", (r) => r.abort("connectionrefused"));
  await page.route("**/api/ready", (r) => r.fulfill({ status: 200, json: { ready: true } }));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 200, json: { user: REVIEWER, expires_at: Math.floor(Date.now() / 1000) + 3600 } }));
  await page.goto("/");
  await expect(page.getByRole("status").filter({ hasText: "API offline" }).first()).toBeVisible();
  await page.locator("#fleet").scrollIntoViewIfNeeded();
  await expect(page.getByRole("heading", { level: 2 }).filter({ hasText: /shipments/i }).first()).toContainText(/\d+\s+of\s+\d+/);
  await expect(page.locator("footer")).toContainText("Recorded run (API offline)");
});

test("a static host that answers every path with index.html is not mistaken for the API", async ({ page }) => {
  const errors = collectErrors(page);
  await page.route("**/api/**", (r) => r.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>spa</title>" }));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/late at the hub/i);
  await expect(page.getByRole("status").filter({ hasText: "Recorded run" }).first()).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "API offline" })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("signing out after a fallback still ends the server session", async ({ page }) => {
  let logouts = 0;
  await page.route("**/api/v1/**", (r) => r.abort("connectionrefused"));
  await page.route("**/api/ready", (r) => r.fulfill({ status: 200, json: { ready: true } }));
  await page.route("**/api/v1/auth/me", (r) => r.fulfill({ status: 200, json: { user: REVIEWER, expires_at: Math.floor(Date.now() / 1000) + 3600 } }));
  await page.route("**/api/v1/auth/logout", (r) => (logouts++, r.fulfill({ status: 204 })));
  await page.goto("/");
  await expect(page.getByRole("status").filter({ hasText: "API offline" }).first()).toBeVisible();
  await page.getByRole("button", { name: /sign out aiqon reviewer/i }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/sign in/i);
  expect(logouts).toBe(1);
});

test("an expired session (401) returns to sign-in with a notice", async ({ page }) => {
  let me = 0;
  await page.route("**/api/v1/**", (r) => r.fulfill({ status: 401, json: { detail: "session expired" } }));
  await page.route("**/api/ready", (r) => r.fulfill({ status: 200, json: { ready: true } }));
  await page.route("**/api/v1/auth/me", (r) =>
    me++ === 0
      ? r.fulfill({ status: 200, json: { user: REVIEWER, expires_at: Math.floor(Date.now() / 1000) + 3600 } })
      : r.fulfill({ status: 401, json: { detail: "session expired" } }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/sign in/i);
  await expect(page.getByText(/session ended/i)).toBeVisible();
});

test("@mobile has no horizontal overflow and a working navigation drawer", async ({ page }) => {
  await page.goto("/?source=snapshot");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await visitAllSections(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  await page.evaluate(() => scrollTo(0, 0));
  const menuButton = page.getByRole("button", { name: /open navigation/i });
  await menuButton.click();
  const drawer = page.getByRole("dialog", { name: "Navigation" });
  await expect(drawer.getByRole("navigation", { name: "Sections" }).getByRole("link")).toHaveCount(6);
  await expect(drawer.getByRole("status").filter({ hasText: "Recorded run" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(menuButton).toBeFocused();
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");

  // Choosing a section closes the drawer and keyboard focus continues from that section.
  await menuButton.click();
  await drawer.getByRole("link", { name: /^alerts/i }).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator("#alerts")).toBeInViewport({ ratio: 0.05 });
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest("#alerts"))).toBe(true);

  // Drawer, then palette on top, then one Escape: the page must not stay scroll-locked.
  await menuButton.click();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("combobox", { name: /search sections/i })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
});

test("command palette finds a shipment by ID and opens it", async ({ page }) => {
  await page.goto("/?source=snapshot");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.keyboard.press("Control+k");
  const box = page.getByRole("combobox", { name: /search sections/i });
  await expect(box).toBeFocused();
  await expect(page.getByRole("listbox").getByRole("option").first()).toBeVisible();
  // Group labels sit inside groups and the empty state outside the listbox (valid combobox structure).
  const { violations } = await new AxeBuilder({ page }).include('[role="dialog"]').analyze();
  expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);

  await box.fill("SHP-000174");
  const option = page.getByRole("listbox", { name: "Results" }).getByRole("option", { name: /SHP-000174/ });
  await expect(option).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("#shipment")).toBeInViewport({ ratio: 0.05 });
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest("#shipment"))).toBe(true);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe("");

  await page.keyboard.press("Control+k");
  await box.fill("zzzz-no-such-thing");
  await expect(page.getByText(/nothing matches/i)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

for (const theme of ["dark", "light"] as const) {
  test(`has no serious or critical accessibility violations (${theme} theme)`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("cascade-theme", t), theme);
    await page.goto("/?source=snapshot");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await visitAllSections(page);
    const { violations } = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    const blocking = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    // Readable failure report: rule, node, and for contrast the measured colours and ratio.
    const report = blocking.flatMap((v) =>
      v.nodes.slice(0, 6).map((n) => {
        const d = n.any[0]?.data as { fgColor?: string; bgColor?: string; contrastRatio?: number } | undefined;
        const extra = d?.contrastRatio ? ` fg ${d.fgColor} on ${d.bgColor} = ${d.contrastRatio}:1` : "";
        return `${v.id} (${v.impact}) ${n.target.join(" ")}${extra}`;
      }),
    );
    expect(report).toEqual([]);
  });
}
