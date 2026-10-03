import os
import pytest

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "harma", "ui", "web")

def test_logo_assets_exist():
    required_files = [
        "harma-logo.png",
        "harma-logo-dark.png",
        "favicon.png",
        "favicon.ico"
    ]
    for filename in required_files:
        path = os.path.join(WEB_DIR, filename)
        assert os.path.exists(path), f"Asset {filename} does not exist in {WEB_DIR}"
        assert os.path.getsize(path) > 100, f"Asset {filename} is too small or empty"

def test_index_html_logo_references():
    index_path = os.path.join(WEB_DIR, "index.html")
    assert os.path.exists(index_path)
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "/static/favicon.png" in content
    assert "/static/favicon.ico" in content
    assert "/static/harma-logo.png" in content
    assert 'class="harma-logo-img"' in content
    assert 'class="harma-hero-logo-img"' in content

def test_style_css_logo_animations():
    css_path = os.path.join(WEB_DIR, "style.css")
    assert os.path.exists(css_path)
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert ".harma-logo-img" in content
    assert ".harma-hero-logo-img" in content
    assert ".harma-avatar-img" in content
    assert "harma-brand-pulse" in content
    assert "harma-hero-float" in content
    assert "harma-thinking-orbit" in content
    assert "harma-hero-float-light" in content

def test_app_js_avatar_uses_logo():
    js_path = os.path.join(WEB_DIR, "app.js")
    assert os.path.exists(js_path)
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "/static/harma-logo.png" in content
    assert "harma-avatar-img" in content
