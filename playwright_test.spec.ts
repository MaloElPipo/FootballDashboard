
import { test, expect } from "@playwright/test";

test("Verify lineup pitch component formations", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", msg => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  await page.goto("http://localhost:5000");
  
  // 1. Navigate to "🔮 Prédiction Buteurs"
  await page.getByText("🔮 Prédiction Buteurs").click();
  
  // 2. Open first match drill-down
  const matchExpander = page.locator("div[data-testid='stExpander']").filter({ hasText: /vs| - / }).first();
  await matchExpander.waitFor({ state: "visible", timeout: 20000 });
  
  const expanderHeader = matchExpander.locator("summary");
  await expanderHeader.click();

  // 3. Find and scroll into interactive expander
  const interactiveExpander = page.locator("div[data-testid='stExpander']").filter({ hasText: "🥅 [T023 c4] Composition manuelle interactive" });
  await interactiveExpander.scrollIntoViewIfNeeded();
  
  // The component is in an iframe. Use title from code.
  const frame = page.frameLocator("iframe[title='live.components.lineup_pitch.render_lineup_pitch']");
  
  // Wait for the iframe content to load
  const formationSelect = frame.locator("select");
  await formationSelect.waitFor({ state: "visible", timeout: 45000 });

  // 4. Verify home formation
  const homeFormation = await formationSelect.inputValue();
  console.log("Home Formation Default:", homeFormation);

  // Take screenshot of Home lineup
  await frame.locator("body").screenshot({ path: "home_lineup.png" });

  // 5. Switch to Away side
  // Find a button that is NOT the currently selected side.
  // The selected side button has background: white or aria-pressed=true
  const awayBtn = frame.getByRole("button").filter({ hasText: /Arsenal|Atlético|Away|Home/ }).nth(1);
  await awayBtn.click();
  
  await page.waitForTimeout(1000);
  const awayFormation = await formationSelect.inputValue();
  console.log("Away Formation Default:", awayFormation);
  
  // Take screenshot of Away lineup
  await frame.locator("body").screenshot({ path: "away_lineup.png" });

  // 6. Confirm 10 formation options exist including 3-4-2-1
  const options = frame.locator("option");
  const optionList = await options.allInnerTexts();
  console.log("Formation options:", optionList);
  console.log("Formation options count:", optionList.length);
  
  expect(optionList.length).toBe(10);
  expect(optionList.some(o => o.includes("3-4-2-1"))).toBe(true);

  console.log("Console Errors:", consoleErrors);
});
