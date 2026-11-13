import os
def sanitize_uploaded_filename(filename: str) -> str:
    clean = os.path.basename(filename.replace('\\', '/'))
    clean = clean.replace('\x00', '')
    while clean.startswith('.'):
        clean = clean[1:]
    return clean or 'unnamed_file'
