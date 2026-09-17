"""Private command-line worker, executed by the LibreOffice-compatible Python.

LibreOffice API: XDocumentIndexesSupplier/XDocumentIndex.update,
XTextFieldsSupplier/XRefreshable.refresh, and XStorable.storeAsURL.
Only the isolated server started by technoeconomic_docx_refresh is contacted.
"""
import json
from pathlib import Path
import sys
import time


def main():
    import uno
    from com.sun.star.beans import PropertyValue

    def properties(**values):
        result = []
        for name, value in values.items():
            item = PropertyValue()
            item.Name, item.Value = name, value
            result.append(item)
        return tuple(result)

    port, source, target, pdf, manifest = sys.argv[1:]
    context = uno.getComponentContext()
    resolver = context.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver', context)
    # A fresh isolated profile can spend time registering Writer extensions.
    # The parent also enforces its 120-second deadline for the entire export.
    deadline = time.monotonic() + 90
    while True:
        try:
            remote = resolver.resolve(f'uno:socket,host=127.0.0.1,port={int(port)};urp;StarOffice.ComponentContext')
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError('The isolated LibreOffice server did not become ready.')
            time.sleep(.2)
    desktop = remote.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop', remote)
    def open_document(path):
        return desktop.loadComponentFromURL(Path(path).as_uri(), '_blank', 0, properties(
            Hidden=True, ReadOnly=False,
            MacroExecutionMode=uno.getConstantByName('com.sun.star.document.MacroExecMode.NEVER_EXECUTE'),
            UpdateDocMode=uno.getConstantByName('com.sun.star.document.UpdateDocMode.NO_UPDATE')))

    def refresh(document):
        if document is None:
            raise RuntimeError('LibreOffice could not open the generated document.')
        prior, stable = None, False
        for _ in range(5):
            document.refresh()
            document.getTextFields().refresh()
            indexes = document.getDocumentIndexes()
            if indexes.getCount() != 1:
                raise RuntimeError('The generated document must contain one editable contents index.')
            for index in range(indexes.getCount()):
                indexes.getByIndex(index).update()
            cursor = document.getCurrentController().getViewCursor()
            cursor.jumpToLastPage()
            count = cursor.getPage()
            signature = (count, indexes.getByIndex(0).getAnchor().getString())
            if signature == prior:
                stable = True
                break
            prior = signature
        if not stable:
            raise RuntimeError('Contents pagination did not converge after five updates.')
        return count, signature[1]

    document = None
    try:
        document = open_document(source)
        refresh(document)
        document.storeAsURL(Path(target).as_uri(), properties(FilterName='Office Open XML Text', Overwrite=True))
        document.close(True)
        document = open_document(target)
        count, contents_text = refresh(document)
        document.store()
        cursor = document.getCurrentController().getViewCursor()
        bookmarks = document.getBookmarks()
        bookmark_pages = {}
        for name in bookmarks.getElementNames():
            cursor.gotoRange(bookmarks.getByName(name).getAnchor().getStart(), False)
            bookmark_pages[name] = cursor.getPage()
        document.storeToURL(Path(pdf).as_uri(), properties(FilterName='writer_pdf_Export', Overwrite=True))
        Path(manifest).write_text(json.dumps({'page_count': count, 'contents_stable': True,
                                            'contents_text': contents_text,
                                            'bookmark_pages': bookmark_pages}, indent=2), encoding='utf-8')
    finally:
        if document is not None:
            document.close(True)
        desktop.terminate()


if __name__ == '__main__':
    main()
