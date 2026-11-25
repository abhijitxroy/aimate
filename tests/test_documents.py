import base64
import io
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from app.documents import ingest,save,read
from app.private_chat import PrivateChat
from app.store import Store
from app.attachment_limits import document_bytes
from app.attachments import decode_file
from test_app import create_app


def item(name,data):
    return {"name":name,"data":base64.b64encode(data).decode()}


def zipped(entries,compression=zipfile.ZIP_STORED):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w",compression=compression) as file:
        for name,value in entries: file.writestr(name,value)
    return stream.getvalue()


class DocumentTests(unittest.TestCase):
    def test_larger_document_http_upload_encrypted_storage_and_legacy_limit(self):
        raw=zipped([("word/document.xml",'<document><t>Large upload evidence</t></document>'),
                    ("word/media/one.bin",b"x"*(3*1024*1024)),
                    ("word/media/two.bin",b"x"*(3*1024*1024))])
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"]
                headers={"X-CSRF-Token":csrf}
                self.assertEqual(client.get("/api/state").json()["attachment_limits"]["document_bytes"],20*1024*1024)
                response=client.post("/api/attachments/document",headers=headers,json=item("large.docx",raw))
                self.assertEqual(response.status_code,200,response.text)
                document=response.json()
                cid=store.new_conversation()
                manifest=save(store,cid,[document])
                self.assertIn("Large upload evidence",read(store,cid,{"id":manifest[0]["id"]})["text"])
                with patch.dict("os.environ",{"AIMATE_LARGE_UPLOADS_ENABLED":"0"}):
                    self.assertEqual(document_bytes(),4*1024*1024)
                    self.assertEqual(client.get("/api/state").json()["attachment_limits"]["document_bytes"],4*1024*1024)
                    self.assertEqual(client.post("/api/attachments/document",headers=headers,json=item("large.docx",raw)).status_code,413)
            store.db.close()
        with self.assertRaisesRegex(ValueError,"20 MB"):
            decode_file(item("too-large.txt",b"x"*(20*1024*1024+1)),document_bytes())

    def test_zip_validates_paths_bombs_and_binary_entries_before_reading(self):
        text=ingest(item("demo.zip",zipped([("src/app.py","print('hello')"),("binary.dat",b"\xff\0")])))
        self.assertIn("print('hello')",text["text"])
        self.assertIn("Binary entry",text["text"])
        for entries in [[("../secret.txt","x")],[("C:/file","x")],[("a","x"),("A","x")]]:
            with self.assertRaisesRegex(ValueError,"unsafe"): ingest(item("bad.zip",zipped(entries)))
        with self.assertRaisesRegex(ValueError,"compression-ratio"):
            ingest(item("bomb.zip",zipped([("huge","x"*100000)],zipfile.ZIP_DEFLATED)))
        with self.assertRaisesRegex(ValueError,"500"):
            ingest(item("many.zip",zipped([(str(n),"x") for n in range(501)])))

    def test_office_xml_and_scanned_pdf_rasterization(self):
        office=ingest(item("note.docx",zipped([("word/document.xml",
            '<w:document xmlns:w="urn:word"><w:p><w:t>Office note</w:t></w:p></w:document>')])))
        self.assertEqual(office["text"],"File: word/document.xml\nOffice note")
        sheet=ingest(item("sheet.xlsx",zipped([
            ("xl/sharedStrings.xml",'<sst><si><t>Meaningful</t></si></sst>'),
            ("xl/worksheets/sheet1.xml",'<worksheet><row><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></row></worksheet>')])))
        self.assertIn("A1=Meaningful | B1=42",sheet["text"])
        with self.assertRaisesRegex(ValueError,"entities"):
            ingest(item("bad.docx",zipped([("word/document.xml",'<!DOCTYPE x [<!ENTITY x "bad">]><x/>')])))
        image=Image.new("RGB",(320,200),"white")
        raw=io.BytesIO();image.save(raw,"PDF")
        scan=ingest(item("scan.pdf",raw.getvalue()))
        self.assertEqual(len(scan["images"]),1)
        self.assertIn("vision",scan["notice"])
        with self.assertRaises(ValueError): ingest(item("bad.pdf",b"not a pdf"))

    def test_large_text_encrypted_paging_search_reopen_and_private_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            cid=store.new_conversation()
            doc=ingest(item("log.txt",("start\n"+"evidence\n"*10000+"needle-last").encode()))
            manifest=save(store,cid,[{k:doc[k] for k in ("name","text","size","kind","notice")}])
            ident=manifest[0]["id"]
            self.assertNotIn("needle-last",str(store.rows("SELECT encrypted FROM documents")))
            first=read(store,cid,{"id":ident})
            self.assertFalse(first["complete"])
            found=read(store,cid,{"id":ident,"search":"needle-last"})
            self.assertIn("needle-last",found["text"])
            with self.assertRaises(ValueError): read(store,store.new_conversation(),{"id":ident})
            private=PrivateChat(store,"private")
            secret=save(private,"private",[{"name":"secret.txt","text":"private-only","size":12,"kind":"text","notice":""}])
            self.assertEqual(read(private,"private",{"id":secret[0]["id"]})["text"],"private-only")
            self.assertEqual(store.rows("SELECT count(*) AS n FROM documents")[0]["n"],1)
            store.db.close()
            store=Store(directory)
            self.assertIn("needle-last",read(store,cid,{"id":ident,"search":"needle-last"})["text"])
            store.db.close()

    def test_document_http_validation_and_unsupported_binary_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with TestClient(create_app(store)) as client:
                csrf=client.post("/api/login",json={"password":store.password}).json()["csrf"]
                headers={"X-CSRF-Token":csrf}
                self.assertEqual(client.post("/api/attachments/document",headers=headers,json=item("bad.zip",b"bad")).status_code,400)
                response=client.post("/api/attachments/document",headers=headers,json=item("file.bin",b"\xff\0"))
                self.assertEqual(response.status_code,200)
                self.assertIn("Metadata only",response.json()["notice"])
                too_big={"name":"big","data":"a"*(28*1024*1024)}
                rejected=client.post("/api/attachments/document",headers=headers,json=too_big)
                self.assertEqual(rejected.status_code,413)
                self.assertIn("20 MB",rejected.json()["detail"])
            store.db.close()
