import io
import re
from pathlib import Path

import tiktoken
from pypdf import PdfReader

from .errors import AppError

MAX_UPLOAD = 10 * 1024 * 1024


def extract(filename, content):
    extension = Path(filename).suffix.lower()
    if extension not in ('.txt', '.md', '.pdf'):
        raise AppError(415, 'unsupported_file', 'Upload a TXT, Markdown (.md), or text-based PDF file.')
    if len(content) > MAX_UPLOAD:
        raise AppError(413, 'file_too_large', 'Files must be 10 MB or smaller.')
    if not content:
        raise AppError(422, 'empty_file', 'The uploaded file is empty.')
    try:
        if extension == '.pdf':
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise AppError(422, 'encrypted_pdf', 'Upload a PDF without password protection.')
            pages = [page.extract_text() or '' for page in reader.pages]
            text = '\n\f\n'.join(pages)
            if not text.strip():
                raise AppError(422, 'image_only_pdf', 'This PDF has no selectable text. Scanned documents are not supported.')
        else:
            text = content.decode('utf-8-sig')
            if '\x00' in text:
                raise ValueError('binary text')
    except AppError:
        raise
    except Exception:
        raise AppError(422, 'corrupt_file', 'The file could not be read. Use UTF-8 text or a valid text-based PDF.') from None
    if not text.strip():
        raise AppError(422, 'empty_file', 'The document contains no readable text.')
    return text


def chunks(text, is_pdf=False):
    encoding = tiktoken.get_encoding('cl100k_base')
    result = []
    for page, page_text in enumerate(text.split('\f'), 1):
        section = ''
        # Keep headings with their sections; split long sections into overlapping windows.
        sections = re.split(r'(?m)(?=^#{1,6} )', page_text)
        for part in sections:
            if not part.strip():
                continue
            heading = re.match(r'^#{1,6}\s+(.+)', part)
            if heading:
                section = heading.group(1).strip()
                if not part[heading.end():].strip():
                    continue
            tokens = encoding.encode(part, disallowed_special=())
            for start in range(0, len(tokens), 600):
                snippet = encoding.decode(tokens[start:start+700]).strip()
                if snippet:
                    result.append({'snippet': snippet, 'section': section, 'page': page if is_pdf else 0})
                if start + 700 >= len(tokens):
                    break
    return result
