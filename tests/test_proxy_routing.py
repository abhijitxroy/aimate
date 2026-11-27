"""Exercise the real PowerShell routing module without corporate network calls."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell routing is covered by the Windows workflow")
class ProxyRoutingTests(unittest.TestCase):
    def run_script(self, script):
        module = str(ROOT / "tools/proxy_routing.ps1").replace("'", "''")
        script = f"$ErrorActionPreference='Stop'\n. '{module}'\n" + script
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        # Scope execution policy to this isolated test process; no machine/user change.
        result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive",
                                 "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError("Routing failed: " + result.stderr)
        return json.loads(result.stdout)

    def plan(self, *, inherited="", all_proxy="", no_proxy="", disabled=False, fail=False):
        options = {
            "urls": ["https://jira.example.test", "https://jenkins.example.test/controller",
                     "https://api.github.com"],
            "inherited": inherited, "all": all_proxy, "no": no_proxy,
            "disabled": disabled, "fail": fail,
        }
        data = base64.b64encode(json.dumps(options).encode()).decode()
        script = f"""
$inputOptions=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{data}')) | ConvertFrom-Json
$resolver={{ param($target)
  if ($inputOptions.fail) {{ throw 'Resolver unavailable' }}
  if ($target.Host -eq 'api.github.com') {{ return [uri]'http://proxy.example.test:8080' }}
  return $target
}}.GetNewClosure()
Get-AiMateProxyRoutes -ConnectionUrls $inputOptions.urls -HttpsProxy $inputOptions.inherited `
  -AllProxy $inputOptions.all -NoProxy $inputOptions.no -ResolveProxy $resolver `
  -Disabled:$inputOptions.disabled | ConvertTo-Json -Compress
"""
        return self.run_script(script)

    def test_system_resolver_does_not_mistake_inherited_proxy_environment_for_windows_policy(self):
        result = self.run_script("""
$env:HTTPS_PROXY='http://inherited.example.test'
$env:HTTP_PROXY='http://inherited.example.test'
$env:ALL_PROXY='http://inherited.example.test'
$env:NO_PROXY='inherited.test'
$route=Get-AiMateSystemProxyRoute -Target 'https://jira.example.test' -ProxyFactory {
  if ($env:HTTPS_PROXY -or $env:HTTP_PROXY -or $env:ALL_PROXY -or $env:NO_PROXY) {
    throw 'Factory was contaminated by inherited routes'
  }
  $resolver=New-Object PSObject
  $resolver | Add-Member ScriptMethod GetProxy {
    param($target)
    if ($env:HTTPS_PROXY -or $env:HTTP_PROXY -or $env:ALL_PROXY -or $env:NO_PROXY) {
      return [uri]'http://inherited.example.test'
    }
    return $target
  }
  return $resolver
}
@{route=$route.AbsoluteUri;https=$env:HTTPS_PROXY;http=$env:HTTP_PROXY;
  all=$env:ALL_PROXY;no=$env:NO_PROXY} | ConvertTo-Json -Compress
""")
        self.assertEqual(result["route"], "https://jira.example.test/")
        for name in ("https", "http", "all"):
            self.assertEqual(result[name], "http://inherited.example.test")
        self.assertEqual(result["no"], "inherited.test")

    def test_system_resolver_failure_restores_inherited_environment(self):
        result = self.run_script("""
$env:HTTPS_PROXY='http://inherited.example.test'
$env:NO_PROXY='inherited.test'
try {
  Get-AiMateSystemProxyRoute -Target 'https://jira.example.test' `
    -ProxyFactory { throw 'System routing unavailable' } | Out-Null
} catch { $message=$_.Exception.Message }
@{message=$message;https=$env:HTTPS_PROXY;no=$env:NO_PROXY} | ConvertTo-Json -Compress
""")
        self.assertEqual(result["message"], "System routing unavailable")
        self.assertEqual(result["https"], "http://inherited.example.test")
        self.assertEqual(result["no"], "inherited.test")

    def test_inherited_https_proxy_preserves_direct_jira_and_jenkins_on_every_restart(self):
        first = self.plan(inherited="http://inherited.example.test:8080")
        second = self.plan(inherited=first["HttpsProxy"], no_proxy=first["NoProxy"])
        self.assertEqual(first, second)
        self.assertEqual(first["HttpsProxy"], "http://inherited.example.test:8080")
        self.assertEqual(set(first["NoProxy"].split(",")),
                         {"127.0.0.1", "localhost", "jira.example.test", "jenkins.example.test"})

    def test_automatic_external_proxy_keeps_internal_routes_and_existing_bypasses(self):
        plan = self.plan(no_proxy=" custom.example.test,localhost,custom.example.test ")
        self.assertEqual(plan["HttpsProxy"], "http://proxy.example.test:8080/")
        hosts = plan["NoProxy"].split(",")
        self.assertEqual(hosts.count("localhost"), 1)
        self.assertEqual(hosts.count("custom.example.test"), 1)
        self.assertIn("jira.example.test", hosts)
        self.assertNotIn("api.github.com", hosts)

    def test_all_proxy_is_not_replaced_but_intranet_still_bypasses_it(self):
        plan = self.plan(all_proxy="http://explicit.example.test:8080")
        self.assertEqual(plan["HttpsProxy"], "")
        self.assertIn("jenkins.example.test", plan["NoProxy"].split(","))

    def test_disabled_routing_preserves_managed_environment_without_resolving(self):
        plan = self.plan(inherited="http://managed.example.test", no_proxy="managed.test",
                         disabled=True, fail=True)
        self.assertEqual(plan, {"HttpsProxy": "http://managed.example.test", "NoProxy": "managed.test"})

    def test_resolver_failure_is_reported_instead_of_silently_changing_routes(self):
        with self.assertRaisesRegex(RuntimeError, "Resolver unavailable"):
            self.plan(fail=True)
