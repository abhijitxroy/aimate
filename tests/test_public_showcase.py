import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from test_app import create_app, Store
from app.public_showcase import PublicPolicy, prepare_directory
from app.validation import validate_config
from app.connectors import Services
from app.repository_settings import prepare_repository


class PublicShowcaseTests(unittest.TestCase):
    def personal_config(self):
        return {"allow_writes":False,"github":{"url":"https://api.github.com","repos":["abhijitxroy/aimate"]}}

    def test_rejects_intel_and_unapproved_sources_including_url_normalization(self):
        with patch.dict(os.environ,{"AIMATE_PUBLIC_SHOWCASE":"1"}):
            for owner in ("intel","intel-innersource","another-owner"):
                with self.assertRaisesRegex(ValueError,"blocked"):
                    validate_config({"github":{"url":"https://github.com/"+owner,
                                             "repos":["repo"]}}, {})
            for host in ("jira.devtools.intel.com","cje-fm-owrp-prod01.devtools.intel.com","unapproved.example"):
                with self.assertRaisesRegex(ValueError,"blocked"):
                    PublicPolicy().validate({"jira":{"url":"https://"+host}})
            result = validate_config(self.personal_config(),{})
            self.assertEqual(result["github"]["repos"],["abhijitxroy/aimate"])
            self.assertTrue(result["_public_showcase"])

    def test_non_intel_jira_requires_explicit_operator_allowlist(self):
        with patch.dict(os.environ,{"AIMATE_PUBLIC_JIRA_HOSTS":"personal.atlassian.net"}):
            PublicPolicy().validate({"jira":{"url":"https://personal.atlassian.net","token":"fictional"}})
            with self.assertRaises(ValueError):
                PublicPolicy().validate({"jira":{"url":"https://jira.devtools.intel.com"}})

    def test_existing_dataset_refused_and_fresh_marker_reused(self):
        with tempfile.TemporaryDirectory() as path:
            (Path(path)/"existing-chat.txt").write_text("local history")
            with self.assertRaisesRegex(ValueError,"fresh"):
                prepare_directory(path)
        with tempfile.TemporaryDirectory() as path:
            prepare_directory(path)
            store=Store(path)
            try:
                prepare_directory(path)
                self.assertEqual(store.rows("SELECT * FROM conversations"),[])
            finally:
                store.db.close()

    def test_intel_repo_proposal_refused_before_network(self):
        config={**self.personal_config(),"_public_showcase":True}
        def network(cfg):
            self.fail("Blocked repo must never reach connection checking.")
        with self.assertRaisesRegex(ValueError,"blocked"):
            asyncio.run(prepare_repository(config,{"repo":"intel-innersource/private-repo"},network))

    def test_source_response_with_intel_resource_is_not_returned(self):
        config={**self.personal_config(),"_public_showcase":True}
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
            "body":"See https://jira.devtools.intel.com/browse/PRIVATE-1"}))
        with self.assertRaisesRegex(ValueError,"Intel"):
            asyncio.run(Services(config,transport).read("github","/repos/abhijitxroy/aimate/issues/1"))

    def test_encoded_github_file_cannot_hide_intel_resource_links(self):
        import base64
        encoded=base64.b64encode(b"https://jira.devtools.intel.com/browse/PRIVATE-1").decode()
        with self.assertRaisesRegex(ValueError,"Intel"):
            PublicPolicy().text({"encoding":"base64","content":encoded})

    def test_public_app_has_clean_state_blocks_intel_inputs_and_keeps_local_app_unchanged(self):
        with tempfile.TemporaryDirectory() as path, patch.dict(os.environ,{
                "APP_DATA_DIR":path,"AIMATE_PUBLIC_SHOWCASE":"1","AIMATE_ENV":"development"}):
            app=create_app()
            store=app.state.store
            client=TestClient(app)
            try:
                login=client.post("/api/login",json={"password":store.password})
                headers={"x-csrf-token":login.json()["csrf"]}
                self.assertEqual(client.get("/api/state").json()["conversations"],[])
                self.assertEqual(client.put("/api/settings/github",headers=headers,json={
                    "url":"https://api.github.com","repos":["intel-innersource/private"]}).status_code,400)
                self.assertEqual(client.put("/api/settings/github",headers=headers,json={
                    "url":"https://api.github.com","repos":["abhijitxroy/aimate"]}).status_code,200)
                cid=client.post("/api/conversations",headers=headers).json()["id"]
                self.assertEqual(client.post("/api/chat",headers=headers,json={
                    "conversation":cid,"question":"Read https://github.com/intel-innersource/private"}).status_code,400)
                self.assertEqual(client.post("/api/knowledge",headers=headers,json={
                    "key":"Intel ticket","value":"https://jira.devtools.intel.com/browse/PRIVATE-1"}).status_code,400)
                grant=client.post("/api/access/grants",headers=headers,json={"role":"viewer","name":"Public user"}).json()
                reader=TestClient(app)
                try:
                    response=reader.post("/api/access/login",json={"role":"viewer","code":grant["code"]})
                    rh={"x-csrf-token":response.json()["csrf"]}
                    self.assertEqual(reader.put("/api/settings/github",headers=rh,json={
                        "url":"https://api.github.com","repos":["intel/private"]}).status_code,400)
                finally:
                    reader.close()
            finally:
                client.close()
                app.state.workspaces.close()
                store.db.close()
