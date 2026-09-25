from app.updates import _release_from_payload, version_tuple


def test_version_tuple_accepts_common_github_tag_forms():
    expected = (2, 5, 12)
    for value in ("2.5.12", "v2.5.12", "v.2.5.12", ".2.5.12"):
        assert version_tuple(value) == expected


def test_release_normalizes_v_dot_tag():
    release = _release_from_payload(
        {
            "tag_name": "v.2.5.12",
            "assets": [
                {
                    "name": "vps-bill-2.5.12.tar.gz",
                    "browser_download_url": "https://example.invalid/vps-bill-2.5.12.tar.gz",
                }
            ],
        }
    )
    assert release.version == "2.5.12"
    assert release.asset_url.endswith("vps-bill-2.5.12.tar.gz")
