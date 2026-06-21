from app.utils.files import build_temp_upload_path, sanitize_filename


def test_sanitize_filename_strips_path_components_for_posix_and_windows():
    assert sanitize_filename('../../secret/report.pdf') == 'report.pdf'
    assert sanitize_filename(r'C:\\temp\\nested\\notes.txt') == 'notes.txt'


def test_sanitize_filename_rejects_empty_or_placeholder_names():
    assert sanitize_filename(None) == 'upload.bin'
    assert sanitize_filename(' ..\x00 ') == 'upload.bin'


def test_build_temp_upload_path_preserves_safe_suffix():
    temp_path, safe_name = build_temp_upload_path('/tmp', '../../archive.md')

    assert safe_name == 'archive.md'
    assert temp_path.startswith('/tmp/upload-')
    assert temp_path.endswith('.md')
