"""Verify the real worker requests Chromium's native process sandbox."""
from playwright.sync_api import BrowserType

from sight_core.capability_worker import browser


def test_untrusted_html_browser_does_not_disable_native_sandbox(monkeypatch):
    actual_launch = BrowserType.launch
    observed = []

    def inspect_launch(self, **kwargs):
        # Permit this read-only diagnostic CDP method; leave sandbox selection
        # exactly as the production worker supplied it.
        kwargs["args"] = [*kwargs.get("args", []), "--enable-automation"]
        instance = actual_launch(self, **kwargs)
        session = instance.new_browser_cdp_session()
        try:
            observed.extend(session.send("Browser.getBrowserCommandLine")["arguments"])
            assert observed and "--no-sandbox" not in observed
        except BaseException:
            instance.close()
            raise
        finally:
            if instance.is_connected():
                session.detach()
        return instance

    monkeypatch.setattr(BrowserType, "launch", inspect_launch)
    result = browser({"html": "<title>Sandbox check</title><p>Local synthetic HTML</p>", "fields": {}})
    assert result["title"] == "Sandbox check"
    assert observed and "--no-sandbox" not in observed
