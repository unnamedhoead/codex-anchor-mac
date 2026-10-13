import json
import pathlib
import subprocess
import sys
import unittest

SERVER = pathlib.Path(__file__).resolve().parent / "anchor_mcp.py"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}


def talk(requests: list) -> list:
    """Drive the server over stdio the way a host would."""
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    p = subprocess.run([sys.executable, str(SERVER)], input=payload,
                       capture_output=True, text=True, timeout=30)
    return [json.loads(line) for line in p.stdout.splitlines() if line.strip()]


class Protocol(unittest.TestCase):
    def test_initialize_advertises_tools_and_resources(self):
        out = talk([INIT])
        caps = out[0]["result"]["capabilities"]
        self.assertIn("tools", caps)
        self.assertIn("resources", caps)

    def test_tools_list_has_the_six_tools(self):
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertEqual(names, {"anchor_status", "anchor_set_time",
                                 "anchor_toggle", "anchor_run_now",
                                 "anchor_install", "anchor_uninstall"})

    def test_status_tool_carries_the_ui_resource(self):
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
        tool = next(t for t in out[1]["result"]["tools"]
                    if t["name"] == "anchor_status")
        self.assertTrue(tool["_meta"]["ui"]["resourceUri"].startswith(
            "ui://codex-anchor-mac/panel-"))

    def test_ui_resource_declares_no_network(self):
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}])
        csp = out[1]["result"]["resources"][0]["_meta"]["ui"]["csp"]
        self.assertEqual(csp["connectDomains"], [])
        self.assertEqual(csp["resourceDomains"], [])

    def test_read_panel_html(self):
        listed = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}])
        uri = listed[1]["result"]["resources"][0]["uri"]
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "resources/read",
                           "params": {"uri": uri}}])
        self.assertIn("<!doctype html", out[1]["result"]["contents"][0]["text"].lower())

    def test_unknown_method_returns_an_error_not_a_crash(self):
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "nope/nope"}])
        self.assertEqual(out[1]["error"]["code"], -32601)

    def test_bad_arguments_return_an_error_not_a_crash(self):
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "anchor_set_time",
                                      "arguments": {"hour": 99, "minute": 0}}}])
        self.assertIn("0-23", out[1]["result"]["content"][0]["text"])

    def test_status_round_trips_as_json(self):
        out = talk([INIT, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "anchor_status", "arguments": {}}}])
        body = json.loads(out[1]["result"]["content"][0]["text"])
        self.assertIn("timezone", body)
        self.assertIn("runs", body)


if __name__ == "__main__":
    unittest.main()
