from sanitizer import sanitize_uploaded_filename
assert sanitize_uploaded_filename('report.pdf') == 'report.pdf'
