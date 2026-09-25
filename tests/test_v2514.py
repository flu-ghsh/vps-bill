from app.updates import _release_from_payload, changelog_section


def test_changelog_section_returns_only_requested_version():
    text = '''# Changelog\n\n## 2.5.14\n\n- First change.\n- Second `change`.\n\n## 2.5.13\n\n- Old change.\n'''
    notes = changelog_section(text, '2.5.14')
    assert notes == '- First change.\n- Second `change`.'
    assert 'Old change' not in notes


def test_changelog_section_accepts_v_header():
    assert changelog_section('## v2.5.14\n\n- ok\n', '2.5.14') == '- ok'


def test_release_body_is_not_used_as_release_notes():
    rel = _release_from_payload({
        'tag_name': 'v2.5.14',
        'body': '**Full Changelog**: https://example.invalid',
        'assets': [{'name': 'vps-bill-2.5.14.tar.gz', 'browser_download_url': 'https://example.invalid/archive'}],
    })
    assert rel.notes == ''
    assert rel.asset_url.endswith('/archive')
