import { expect, test, type Page } from "@playwright/test";

const SEEKER_EMAIL = process.env.TEST_SEEKER_EMAIL || "";
const SEEKER_PASSWORD = process.env.TEST_SEEKER_PASSWORD || "";
const PROVIDER_EMAIL = process.env.TEST_PROVIDER_EMAIL || "";
const PROVIDER_PASSWORD = process.env.TEST_PROVIDER_PASSWORD || "";

let createdBookingId = "";

async function login(page: Page, email: string, password: string) {
  await page.goto("/demo_login");
  await page.getByTestId("email").fill(email);
  await page.getByTestId("password").fill(password);
  await page.getByTestId("login-btn").click();
}

test.describe.serial("marketplace smoke flows", () => {
  test.skip(
    !SEEKER_EMAIL || !SEEKER_PASSWORD || !PROVIDER_EMAIL || !PROVIDER_PASSWORD,
    "Set TEST_SEEKER_EMAIL, TEST_SEEKER_PASSWORD, TEST_PROVIDER_EMAIL, and TEST_PROVIDER_PASSWORD to run Playwright smoke tests."
  );

  test("seeker can search and book a provider", async ({ page }) => {
    await login(page, SEEKER_EMAIL, SEEKER_PASSWORD);
    await page.waitForURL(/\/home$/);

    await page.getByTestId("search-input").fill("plumber");
    await page.getByTestId("search-btn").click();
    await expect(page.getByTestId("provider-card").first()).toBeVisible();

    await page.getByTestId("provider-card").first().getByTestId("book-now-btn").click();
    await page.waitForURL(/\/booking\//);

    await page.locator('[data-testid="slot-chip"]:not([disabled])').first().click();
    await page.getByTestId("confirm-booking-btn").click();

    await expect(page.getByTestId("booking-confirmed")).toBeVisible();
    await expect(page.getByTestId("booking-id")).toContainText("Booking #");

    const bookingLabel = (await page.getByTestId("booking-id").textContent()) || "";
    createdBookingId = bookingLabel.replace("Booking #", "").trim();
    expect(createdBookingId).not.toBe("");
  });

  test("provider can accept a pending booking", async ({ page }) => {
    test.skip(!createdBookingId, "Booking from previous smoke step was not created.");

    await login(page, PROVIDER_EMAIL, PROVIDER_PASSWORD);
    await page.waitForURL(/\/provider\/dashboard$/);

    await expect(page.getByTestId("pending-booking").first()).toBeVisible();
    await page.getByTestId("pending-booking").first().getByTestId("accept-booking-btn").click();
    await expect(page.locator('[data-testid="booking-status"]').filter({ hasText: /confirmed/i }).first()).toBeVisible();
  });

  test("booking chat works live for seeker and provider", async ({ browser }) => {
    test.skip(!createdBookingId, "Booking from previous smoke step was not created.");

    const seekerContext = await browser.newContext();
    const providerContext = await browser.newContext();
    const seekerPage = await seekerContext.newPage();
    const providerPage = await providerContext.newPage();

    await login(seekerPage, SEEKER_EMAIL, SEEKER_PASSWORD);
    await seekerPage.waitForURL(/\/home$/);
    await login(providerPage, PROVIDER_EMAIL, PROVIDER_PASSWORD);
    await providerPage.waitForURL(/\/provider\/dashboard$/);

    await seekerPage.goto(`/chat/booking_${createdBookingId}`);
    await providerPage.goto(`/chat/booking_${createdBookingId}`);

    await seekerPage.getByTestId("message-input").fill("Test message from Playwright");
    await seekerPage.getByTestId("send-btn").click();

    await expect(seekerPage.getByTestId("message-bubble").last()).toContainText("Test message from Playwright");
    await expect(seekerPage.getByTestId("message-status").last()).toBeVisible();
    await expect(providerPage.getByTestId("message-bubble").last()).toContainText("Test message from Playwright");

    await providerPage.getByTestId("message-input").fill("Provider reply from Playwright");
    await providerPage.getByTestId("send-btn").click();

    await expect(providerPage.getByTestId("message-bubble").last()).toContainText("Provider reply from Playwright");
    await expect(seekerPage.getByTestId("message-bubble").last()).toContainText("Provider reply from Playwright");

    await seekerContext.close();
    await providerContext.close();
  });
});
