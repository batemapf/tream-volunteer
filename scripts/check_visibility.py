"""Live read-only check: crawler directives, page title and locally hosted bear."""

import os
import urllib.request

site = os.environ["SITE_URL"]
api = os.environ["API_URL"]
for path in ("/", "/organizer.html", "/assets/brent-bear.png"):
    with urllib.request.urlopen(site + path) as result:
        assert "noindex" in result.headers.get("X-Robots-Tag", ""), (
            "Missing CDN noindex on " + path
        )
        if path.endswith(".html") or path == "/":
            content = result.read().decode()
            assert "2026 Brent Elementary Christmas Tree and Holiday Sale" in content
            assert 'name="robots"' in content and "noindex" in content
            assert "assets/brent-bear.png" in content
with urllib.request.urlopen(site + "/robots.txt") as result:
    text = result.read().decode()
    assert "User-agent: *" in text and "Disallow:" in text
for path in ("/health", "/schedule", "/robots.txt"):
    with urllib.request.urlopen(api + path) as result:
        assert "noindex" in result.headers.get("X-Robots-Tag", ""), (
            "Missing API noindex on " + path
        )
print(
    "PASS: CDN/API noindex headers, HTML robots directives, requested page title, bear asset and robots.txt."
)
