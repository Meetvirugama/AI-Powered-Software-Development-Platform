from sanitizer import sanitize_uploaded_filename
assert sanitize_uploaded_filename('../../etc/passwd') == 'passwd'
assert sanitize_uploaded_filename('..\\windows\\win.ini') == 'win.ini'
