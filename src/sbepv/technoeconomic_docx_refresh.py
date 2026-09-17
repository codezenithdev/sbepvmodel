"""Populate Word field caches with an isolated, bounded LibreOffice process.

This module never changes saved analysis evidence or a user's office profile.
Only generated temporary documents are opened; output is released after checks.
"""
from collections import Counter
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile


W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


class DocxRefreshError(RuntimeError):
    """The Word export cannot safely be delivered with refreshed fields."""


def _executable(config_name, alternatives):
    configured = os.environ.get(config_name)
    candidates = [configured] if configured else alternatives
    for value in candidates:
        if not value:
            continue
        path = shutil.which(str(value)) or (str(value) if Path(value).is_file() else None)
        if path:
            return str(Path(path).resolve())
    raise DocxRefreshError(f'Word export requires LibreOffice and UNO Python. Configure {config_name} on the report server.')


def office_runtime():
    from sbepv.paths import ProjectRootNotFoundError, discover_project_root
    local = {}
    try:
        manifest = discover_project_root(Path(__file__)) / 'tmp/runtime/libreoffice-runtime.json'
        if not (os.environ.get('PV_REPORT_SOFFICE') and os.environ.get('PV_REPORT_UNO_PYTHON')) and manifest.is_file():
            local = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(local, dict):
                raise ValueError('The runtime manifest must be an object.')
    except ProjectRootNotFoundError:
        pass  # An installed package can use the configured or PATH runtime.
    except (OSError, ValueError):
        raise DocxRefreshError('The local Word export runtime manifest is invalid.') from None
    soffice = _executable('PV_REPORT_SOFFICE', [local.get('soffice'), 'soffice', 'libreoffice'])
    console = Path(soffice).with_suffix('.com')
    if os.name == 'nt' and Path(soffice).name.lower() == 'soffice.exe' and console.is_file():
        soffice = str(console)
    program = Path(soffice).parent
    python_candidates = [local.get('uno_python'), program / 'python.exe', *program.glob('python-core-*/bin/python.exe')]
    python_candidates += ['/usr/bin/python3', sys.executable]
    python = _executable('PV_REPORT_UNO_PYTHON', python_candidates)
    return soffice, python


def _fields(root):
    """Read nested complex and simple Word fields, including cached TOC text."""
    result, stack, bookmarks = [], [], {}
    for node in root.iter():
        if node.tag == W + 'bookmarkStart':
            bookmarks[node.get(W + 'id')] = node.get(W + 'name')
        elif node.tag == W + 'bookmarkEnd':
            bookmarks.pop(node.get(W + 'id'), None)
        elif node.tag == W + 'fldSimple':
            result.append({'instruction': node.get(W + 'instr', ''),
                           'result': ''.join(node.itertext()), 'bookmarks': tuple(bookmarks.values()), 'links': []})
        elif node.tag == W + 'fldChar':
            kind = node.get(W + 'fldCharType')
            if kind == 'begin':
                stack.append({'instruction': '', 'result': '', 'separated': False,
                              'bookmarks': tuple(bookmarks.values()), 'links': []})
            elif kind == 'separate' and stack:
                stack[-1]['separated'] = True
            elif kind == 'end' and stack:
                result.append(stack.pop())
        elif node.tag == W + 'instrText' and stack:
            stack[-1]['instruction'] += node.text or ''
        elif node.tag == W + 'hyperlink' and node.get(W + 'anchor'):
            for field in stack:
                if field['separated']:
                    field['links'].append({'anchor': node.get(W + 'anchor'),
                                           'texts': [n.text or '' for n in node.iter(W + 't')]})
        elif node.tag == W + 't':
            for field in stack:
                if field['separated']:
                    field['result'] += node.text or ''
    if stack:
        raise DocxRefreshError('Word export contains an incomplete field.')
    for item in result:
        item['instruction'] = ' '.join(item['instruction'].split())
    return result


def field_inventory(payload):
    try:
        with ZipFile(BytesIO(payload)) as archive:
            fields, bookmarks, headings, heading_bookmarks = [], set(), [], []
            part_fields, document = {}, None
            for name in archive.namelist():
                if not re.fullmatch(r'word/(document|footer\d*|header\d*)\.xml', name):
                    continue
                root = ET.fromstring(archive.read(name))
                part_fields[name] = _fields(root)
                fields.extend(part_fields[name])
                bookmarks.update(node.get(W + 'name') for node in root.iter(W + 'bookmarkStart'))
                if name == 'word/document.xml':
                    document = root
                    for paragraph in root.iter(W + 'p'):
                        style = paragraph.find(W + 'pPr/' + W + 'pStyle')
                        if style is not None and re.fullmatch(r'Heading[123]', style.get(W + 'val', '')):
                            text = ''.join(n.text or '' for n in paragraph.iter(W + 't'))
                            headings.append((style.get(W + 'val'), text))
                            heading_bookmarks.append({'style': style.get(W + 'val'), 'text': text,
                                'bookmarks': [node.get(W + 'name') for node in paragraph.iter(W + 'bookmarkStart')]})
            numbering = archive.read('word/numbering.xml') if 'word/numbering.xml' in archive.namelist() else b''
            relationships = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
            targets = {node.get('Id'): 'word/' + node.get('Target', '').lstrip('/') for node in relationships}
            settings = ET.fromstring(archive.read('word/settings.xml'))
            active_footers = []
            for section in document.iter(W + 'sectPr'):
                types = {'default'}
                if settings.find(W + 'evenAndOddHeaders') is not None:
                    types.add('even')
                if section.find(W + 'titlePg') is not None:
                    types.add('first')
                active_footers.extend(targets.get(node.get(R + 'id')) for node in section.findall(W + 'footerReference')
                                      if node.get(W + 'type') in types)
            return {'fields': fields, 'bookmarks': bookmarks, 'headings': headings,
                    'heading_bookmarks': heading_bookmarks, 'numbering': numbering,
                    'active_footers': active_footers, 'part_fields': part_fields}
    except (BadZipFile, ET.ParseError, KeyError) as exc:
        raise DocxRefreshError('Word export is not a valid editable document.') from exc


def _field_key(instruction):
    words = instruction.split()
    kind = words[0].upper() if words else ''
    if kind in {'SEQ', 'REF'}:
        return kind, words[1].strip('"') if len(words) > 1 else ''
    return kind, ''


def validate_refreshed_docx(original, refreshed):
    before, after = field_inventory(original), field_inventory(refreshed)
    required = Counter(_field_key(f['instruction']) for f in before['fields'])
    actual = Counter(_field_key(f['instruction']) for f in after['fields'])
    for key, count in required.items():
        if key[0] in {'SEQ', 'REF', 'TOC'} and actual[key] != count:
            raise DocxRefreshError(f'Word refresh did not preserve the {key[0]} fields.')
        if key[0] in {'PAGE', 'NUMPAGES'} and actual[key] < count:
            raise DocxRefreshError(f'Word refresh did not preserve the {key[0]} fields.')
    # Writer can materialize equivalent even/default footer parts. Validate the
    # section's active relationships instead of assuming identical ZIP parts.
    if not after['active_footers']:
        raise DocxRefreshError('Word refresh lost the active report footer.')
    for name in after['active_footers']:
        kinds = Counter(_field_key(field['instruction'])[0] for field in after['part_fields'].get(name, []))
        if kinds['PAGE'] != 1 or kinds['NUMPAGES'] != 1:
            raise DocxRefreshError('Word refresh lost the active footer page fields.')
    sequence = lambda inventory: [field['result'].strip() for field in inventory['fields']
                                  if _field_key(field['instruction']) == ('SEQ', 'Figure')]
    if sequence(before) != sequence(after):
        raise DocxRefreshError('Word refresh changed the figure caption sequence.')
    if not before['bookmarks'].issubset(after['bookmarks']):
        raise DocxRefreshError('Word refresh did not preserve report bookmarks.')
    if before['headings'] != after['headings'] or not after['numbering']:
        raise DocxRefreshError('Word refresh did not preserve numbered report headings.')
    contents = [f['result'] for f in after['fields'] if _field_key(f['instruction'])[0] == 'TOC']
    if len(contents) != 1 or not re.search(r'\d', contents[0]):
        raise DocxRefreshError('Word contents did not receive page numbers.')
    if 'Open in Word and update' in contents[0]:
        raise DocxRefreshError('Word contents still contains the unfinished placeholder.')
    for style, text in before['headings']:
        if style == 'Heading1' and text not in contents[0]:
            raise DocxRefreshError('Word contents is missing a major heading.')
    for field in after['fields']:
        if _field_key(field['instruction'])[0] in {'SEQ', 'REF', 'PAGE', 'NUMPAGES'}:
            if not re.fullmatch(r'\s*\d+\s*', field['result']):
                raise DocxRefreshError('Word refresh left an unresolved figure or page field.')
    figure_numbers = {name: field['result'].strip() for field in after['fields']
                      if _field_key(field['instruction']) == ('SEQ', 'Figure')
                      for name in field['bookmarks']}
    for field in after['fields']:
        kind, target = _field_key(field['instruction'])
        if kind == 'REF' and (target not in figure_numbers or field['result'].strip() != figure_numbers[target]):
            raise DocxRefreshError('Word figure references do not match their numbered captions.')


def _stop_owned_process(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


def validate_pagination(original, refreshed, manifest):
    """Tie the editable TOC's cached pages to the same rendered heading anchors."""
    before, after = field_inventory(original), field_inventory(refreshed)
    toc = next(field for field in after['fields'] if _field_key(field['instruction'])[0] == 'TOC')
    entries = {}
    for link in toc['links']:
        entries.setdefault(link['anchor'], []).extend(link['texts'])
    bookmark_pages = manifest.get('bookmark_pages', {})
    for heading in before['heading_bookmarks']:
        if heading['style'] != 'Heading1':
            continue
        matches = [(anchor, texts) for anchor, texts in entries.items()
                   if texts and re.sub(r'^\s*\d+(?:\.\d+)*[.\s]*', '', ''.join(texts[:-1])).strip() == heading['text']
                   and re.fullmatch(r'\d+', texts[-1].strip())]
        if len(matches) != 1:
            raise DocxRefreshError('Word contents did not retain a verifiable page link for each major heading.')
        anchor, texts = matches[0]
        actual_pages = {bookmark_pages[name] for name in heading['bookmarks'] if name in bookmark_pages}
        displayed = int(texts[-1])
        # LibreOffice's internal TOC targets are hidden from UNO's bookmark
        # collection, but are preserved on the actual heading in the DOCX.
        target_headings = [item for item in after['heading_bookmarks']
                           if anchor in item['bookmarks'] and item['style'] == heading['style']
                           and item['text'] == heading['text']
                           and set(heading['bookmarks']).issubset(item['bookmarks'])]
        if not actual_pages or actual_pages != {displayed} or len(target_headings) != 1:
            raise DocxRefreshError('Word contents page numbers do not match the rendered heading pages.')


def refresh_docx_fields(payload, *, qa_pdf_path=None, timeout_seconds=120):
    """Return refreshed DOCX bytes; optionally retain its actual rendered QA PDF."""
    field_inventory(payload)
    soffice, python = office_runtime()
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with tempfile.TemporaryDirectory(prefix='sbepv-word-') as directory:
        root = Path(directory)
        source, target, pdf = root / 'source.docx', root / 'updated.docx', root / 'layout.pdf'
        source.write_bytes(payload)
        profile = root / 'profile'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        command = [soffice, '--headless', '--nologo', '--nodefault', '--norestore', '--nofirststartwizard',
                   '-env:UserInstallation=' + profile.as_uri(),
                   f'--accept=socket,host=127.0.0.1,port={port},tcpNoDelay=1;urp;StarOffice.ComponentContext']
        environment = os.environ.copy()
        program = str(Path(soffice).parent)
        environment['PATH'] = program + os.pathsep + environment.get('PATH', '')
        environment['PYTHONPATH'] = program
        environment['UserInstallation'] = profile.as_uri()
        # Writer exports need no GPU calculation; avoid profiling devices in
        # every new isolated profile (as LibreOffice's own server does).
        environment['SAL_DISABLE_OPENCL'] = 'true'
        environment.pop('PYTHONHOME', None)
        process = worker_process = None
        try:
            with (root / 'office.log').open('wb') as log:
                process = subprocess.Popen(command, cwd=root, stdout=log, stderr=log,
                                           creationflags=flags, env=environment, start_new_session=os.name != 'nt')
                worker = Path(__file__).with_name('technoeconomic_uno_worker.py')
                worker_process = subprocess.Popen([python, str(worker), str(port), str(source), str(target), str(pdf),
                                                   str(root / 'layout.json')], cwd=root, env=environment,
                                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags,
                                                  start_new_session=os.name != 'nt')
                _, worker_error = worker_process.communicate(timeout=timeout_seconds)
            if worker_process.returncode:
                detail = worker_error.decode('utf-8', errors='replace').strip().splitlines()
                raise DocxRefreshError('Word field refresh failed: ' + (detail[-1][:300] if detail else 'LibreOffice UNO worker failed'))
            if not target.is_file() or not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):
                raise DocxRefreshError('Word refresh did not produce a verified document and layout.')
            refreshed = target.read_bytes()
            validate_refreshed_docx(payload, refreshed)
            manifest = json.loads((root / 'layout.json').read_text(encoding='utf-8'))
            if manifest.get('page_count', 0) < 1 or not manifest.get('contents_stable'):
                raise DocxRefreshError('Word pagination did not converge.')
            validate_pagination(payload, refreshed, manifest)
            if any(int(field['result']) != manifest['page_count'] for field in field_inventory(refreshed)['fields']
                   if _field_key(field['instruction'])[0] == 'NUMPAGES'):
                raise DocxRefreshError('Word page-count fields do not match the rendered layout.')
            if qa_pdf_path is not None:
                destination = Path(qa_pdf_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(pdf.read_bytes())
                destination.with_suffix('.layout.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            return refreshed
        except subprocess.TimeoutExpired as exc:
            raise DocxRefreshError('Word field refresh timed out. The unfinished document was not exported.') from exc
        except (OSError, ValueError) as exc:
            raise DocxRefreshError('Word field refresh could not complete. Check the configured LibreOffice and UNO Python runtime.') from exc
        finally:
            if worker_process is not None:
                _stop_owned_process(worker_process)
            if process is not None:
                _stop_owned_process(process)
