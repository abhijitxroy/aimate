import asyncio
import unittest
import httpx
from app.validation import validate_config
from app.connectors import Services
from app.connection_checks import check_connection

class JenkinsSimpleTests(unittest.TestCase):
    def config(self, **changes):
        raw = {"ai": {}, "github": {}, "jira": {}, "jenkins": {
            "url": "https://jenkins.example", "username": "operator", "token": "private-token",
            "mode": "simple", "jobs": [], **changes}}
        return validate_config(raw, {})

    def test_optional_jobs_and_saved_identity(self):
        cfg = self.config()["jenkins"]
        self.assertEqual(cfg["access"], "all")
        self.assertEqual(cfg["jobs"], [])
        self.assertEqual(cfg["username"], "operator")
        self.assertEqual(cfg["url"], "https://jenkins.example")

    def test_empty_jobs_from_legacy_form_connects(self):
        cfg = self.config()
        del cfg["jenkins"]["mode"]
        del cfg["jenkins"]["access"]
        self.assertEqual(validate_config(cfg, {})["jenkins"]["access"], "all")

    def test_discovery_authentication_and_read_only(self):
        calls=[]
        def remote(r):
            calls.append(r)
            if r.url.path.endswith("/whoAmI/api/json"):
                return httpx.Response(200, json={"name": "operator", "authenticated": True})
            self.assertEqual(r.url.params["tree"], "jobs[name,fullName,_class]")
            return httpx.Response(200, json={"jobs": [{"name": "team", "fullName": "team", "_class": "com.cloudbees.hudson.plugins.folder.Folder"}, {"name": "build"}]})
        cfg=self.config()
        report=asyncio.run(check_connection("jenkins",cfg,Services(cfg,httpx.MockTransport(remote)),None,None))
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["targets"]),2)
        self.assertEqual(report["targets"][0]["message"],"Accessible folder")
        self.assertTrue(all(r.method == "GET" for r in calls))
        self.assertNotIn("private-token",str(report))

    def test_nested_job_and_build_paths_and_proposals(self):
        calls=[]
        def remote(r):
            calls.append(r)
            return httpx.Response(200,json={"name":"build"})
        service=Services(self.config(),httpx.MockTransport(remote))
        for path in ("/api/json","/job/team/api/json","/job/team/job/build/api/json","/job/team/job/build/12/api/json","/job/team/job/build/lastBuild/consoleText","/job/team/job/build/12/logText/progressiveText"):
            asyncio.run(service.read("jenkins",path))
        plan=service.plan("jenkins","build_job",{"job":"team/build"})
        self.assertEqual(plan["path"],"/job/team/job/build/build")
        self.assertTrue(all(r.method == "GET" for r in calls))
        self.assertEqual(service.plan("jenkins","abort_build",{"job":"team/build","build":12})["path"],"/job/team/job/build/12/stop")

    def test_admin_and_traversal_endpoints_remain_blocked(self):
        service=Services(self.config())
        for path in ("/scriptText","/credentials/api/json","/computer/api/json","/job/team/config.xml","/job/team/../api/json","/job/team/job/%2e%2e/api/json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                asyncio.run(service.read("jenkins",path))
        for job in ("../build","team/..","team//build","https://other"):
            with self.subTest(job=job),self.assertRaises(ValueError):
                service.plan("jenkins","build_job",{"job":job})

    def test_pipeline_stage_read_respects_scope(self):
        calls = []
        def remote(request):
            calls.append(request)
            return httpx.Response(200, json={"status": "SUCCESS", "stages": [{"name": "Validate", "status": "SUCCESS"}]})
        for cfg in (self.config(), self.config(mode="advanced", access="selected", jobs=["team/build"])):
            svc = Services(cfg, httpx.MockTransport(remote))
            result = asyncio.run(svc.read("jenkins", "/job/team/job/build/11/wfapi/describe"))
            self.assertEqual(result["data"]["stages"][0]["status"], "SUCCESS")
        self.assertTrue(all(request.method == "GET" for request in calls))
        svc = Services(self.config(mode="advanced", access="selected", jobs=["team/build"]))
        for path in ("/job/other/11/wfapi/describe", "/job/team/job/build/11/wfapi/pendingInputActions"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                asyncio.run(svc.read("jenkins", path))

    def test_progressive_log_offsets_cover_all_bytes_without_gaps(self):
        body = (b"warning line\n" * 7200) + b"Finished: SUCCESS\n"
        starts = []
        def remote(request):
            start = int(request.url.params["start"])
            starts.append(start)
            return httpx.Response(200, content=body[start:],
                                  headers={"content-type": "text/plain", "X-Text-Size": str(len(body)), "X-More-Data": "false"})
        svc = Services(self.config(), httpx.MockTransport(remote))
        start, pages = 0, []
        while True:
            data = asyncio.run(svc.read("jenkins", "/job/team/job/build/11/logText/progressiveText", {"start": start}))["data"]
            pages.append(data["text"].encode())
            if not data["more_data"]:
                break
            next_start = int(data["next_start"])
            self.assertGreater(next_start, start)
            start = next_start
        self.assertEqual(b"".join(pages), body)
        self.assertEqual(starts, list(range(0, len(body), 24000)))

    def test_advanced_selected_scope_remains_restricted(self):
        cfg=self.config(mode="advanced",access="selected",jobs=["team/build"])
        service=Services(cfg)
        with self.assertRaises(ValueError):
            service.plan("jenkins","build_job",{"job":"other/build"})
        with self.assertRaises(ValueError):
            asyncio.run(service.read("jenkins","/api/json"))
        with self.assertRaisesRegex(ValueError,"jobs entry"):
            self.config(mode="advanced",access="selected")

    def test_bad_token_and_missing_controller_are_actionable(self):
        cfg=self.config()
        service=Services(cfg,httpx.MockTransport(lambda r: httpx.Response(401)))
        report=asyncio.run(check_connection("jenkins",cfg,service,None,None))
        self.assertFalse(report["ok"])
        self.assertIn("invalid or expired",report["message"])
        cfg["jenkins"]["url"]=""
        report=asyncio.run(check_connection("jenkins",cfg,Services(cfg),None,None))
        self.assertFalse(report["ok"])
        self.assertIn("controller URL",report["message"])

    def test_anonymous_response_does_not_pass(self):
        cfg=self.config()
        service=Services(cfg,httpx.MockTransport(lambda r: httpx.Response(200,json={"name":"anonymous","authenticated":False})))
        report=asyncio.run(check_connection("jenkins",cfg,service,None,None))
        self.assertFalse(report["ok"])
        self.assertIn("did not authenticate",report["message"])

    def test_missing_controller_path_explains_404(self):
        cfg=self.config()
        service=Services(cfg,httpx.MockTransport(lambda r: httpx.Response(404)))
        report=asyncio.run(check_connection("jenkins",cfg,service,None,None))
        self.assertFalse(report["ok"])
        self.assertIn("full controller URL", report["message"])
        self.assertIn("Controller & account", report["message"])
