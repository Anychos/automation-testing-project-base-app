"""Read-only browser smoke for field errors. Run against a seeded local Compose stack."""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect, sync_playwright


def next_weekday():
    day = datetime.now(ZoneInfo("Europe/Moscow")).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def main():
    base_url = os.getenv("BOOKINGLAB_UI_URL", "http://localhost:5173")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        posts = []
        page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
        page.goto(base_url)

        auth = page.get_by_test_id("auth-form")
        assert auth.get_attribute("novalidate") is not None
        page.get_by_test_id("login-submit").click()
        expect(auth.get_by_test_id("auth-email-error")).to_be_visible()
        expect(auth.get_by_test_id("auth-password-error")).to_be_visible()
        expect(auth.get_by_test_id("auth-email")).to_have_attribute("aria-invalid", "true")
        assert not posts
        page.get_by_test_id("auth-email").fill("user@bookinglab.example.com")
        expect(auth.get_by_test_id("auth-email-error")).to_have_count(0)
        expect(auth.get_by_test_id("auth-password-error")).to_be_visible()
        page.get_by_test_id("auth-password").fill("wrongpassword")
        page.get_by_test_id("login-submit").click()
        expect(auth.get_by_test_id("form-error")).to_contain_text("Неверный email или пароль")
        page.get_by_test_id("auth-password").fill("userpassword123")
        page.get_by_test_id("login-submit").click()
        expect(page.get_by_test_id("rooms-screen")).to_be_visible()

        room = page.locator('[data-testid^="room-card-"]').first
        expect(room.get_by_test_id("room-name")).to_be_visible()
        room.get_by_test_id("room-book-button").click()
        booking = page.get_by_test_id("booking-form")
        assert booking.get_attribute("novalidate") is not None
        page.get_by_test_id("booking-start-time").fill("08:30")
        page.get_by_test_id("booking-attendees").fill("0")
        page.get_by_test_id("booking-submit").click()
        for field in ("title", "date", "start-time", "attendees"):
            expect(booking.get_by_test_id(f"booking-{field}-error")).to_be_visible()
        assert not any(url.endswith("/api/bookings") for url in posts)
        page.get_by_test_id("booking-title").fill("Valid meeting")
        expect(booking.get_by_test_id("booking-title-error")).to_have_count(0)
        expect(booking.get_by_test_id("booking-date-error")).to_be_visible()

        page.get_by_test_id("booking-date").fill(next_weekday())
        page.get_by_test_id("booking-start-time").fill("10:00")
        page.get_by_test_id("booking-attendees").fill("1")
        page.route("**/api/bookings", lambda route: route.fulfill(
            status=422, content_type="application/json",
            body=json.dumps({"error": {"code": "VALIDATION_ERROR", "message": "Неверные данные", "fields": [
                {"field": "title", "message": "Ошибка названия от API"},
                {"field": "attendees", "message": "Ошибка участников от API"}
            ]}})
        ))
        page.get_by_test_id("booking-submit").click()
        expect(booking.get_by_test_id("booking-title-error")).to_have_text("Ошибка названия от API")
        expect(booking.get_by_test_id("booking-attendees-error")).to_have_text("Ошибка участников от API")
        page.unroute("**/api/bookings")

        page.get_by_test_id("logout-button").click()
        page.get_by_test_id("auth-email").fill("admin@bookinglab.example.com")
        page.get_by_test_id("auth-password").fill("adminpassword123")
        page.get_by_test_id("login-submit").click()
        page.get_by_test_id("nav-admin").click()
        create = page.get_by_test_id("room-create-form")
        assert create.get_attribute("novalidate") is not None
        create.get_by_test_id("room-create-capacity").fill("1")
        create.get_by_test_id("room-create-price").fill("9999")
        create.get_by_test_id("room-create-submit").click()
        for field in ("name", "capacity", "price"):
            expect(create.get_by_test_id(f"room-create-{field}-error")).to_be_visible()

        editor = page.locator('[data-testid^="room-editor-"]').first
        edit_form = editor.locator('form')
        assert edit_form.get_attribute("novalidate") is not None
        editor.get_by_test_id("room-edit-name").fill("x")
        editor.get_by_test_id("room-edit-capacity").fill("11")
        editor.get_by_test_id("room-edit-price").fill("200001")
        editor.get_by_test_id("room-edit-submit").click()
        for field in ("name", "capacity", "price"):
            expect(editor.get_by_test_id(f"room-edit-{field}-error")).to_be_visible()
        assert not any(url.endswith("/api/rooms") for url in posts)
        browser.close()
    print("UI field validation and test IDs: passed")


if __name__ == "__main__":
    main()
