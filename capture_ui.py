from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8501"

PAGES = [
    "Overview",
    "Incidents",
    "Equipment",
    "Investigate",
    "Ask AegisOps",
    "History",
]

OUTPUT = Path("ui_screenshots")
OUTPUT.mkdir(exist_ok=True)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    page = browser.new_page(
        viewport={"width": 1440, "height": 1000},
        device_scale_factor=1,
    )

    print("Opening AegisOps...")
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    # Screenshot initial Overview
    page.screenshot(
        path=str(OUTPUT / "01_overview.png"),
        full_page=True,
    )
    print("Captured Overview")

    # Capture remaining pages by clicking sidebar navigation
    for number, name in enumerate(PAGES[1:], start=2):
        print(f"Opening {name}...")

        link = page.get_by_role("link", name=name, exact=True)
        link.click()

        # Streamlit rerenders after navigation
        page.wait_for_timeout(2500)

        filename = (
            f"{number:02d}_"
            + name.lower().replace(" ", "_")
            + ".png"
        )

        page.screenshot(
            path=str(OUTPUT / filename),
            full_page=True,
        )

        print(f"Captured {name}")

    browser.close()

print("\nDone. Screenshots are in ui_screenshots/")