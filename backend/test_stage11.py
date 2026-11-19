"""Stage 11 tests — AI Engineering Assistant (end-to-end, real HTTP).

Covers the 12 required categories from the Stage 11 spec:
 1. engineering question answered through the assistant
 2. mechanical calculation via the existing mechanical engine
 3. electrical circuit created and solved via the existing circuit solver
 4. structural calculation via the existing structural engine
 5. material properties from the existing database
 6. existing project inspected with user permission
 7. project modification requiring user approval
 8. two users using their own assistants simultaneously
 9. unauthorized access to another user's project rejected
10. AI API failure handled correctly
11. invalid tool inputs rejected
12. API usage and costs recorded correctly

Run:  cd backend && python3 test_stage11.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as appmod  # noqa: E402
import assistant as assistmod  # noqa: E402
import db as dbmod  # noqa: E402

PASS = []
FAIL = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f" — {detail}" if detail and not ok else ""))


def approx(a, b, rel=0.01):
    return abs(a - b) <= rel * abs(b)


def main():
    tmp = tempfile.mkdtemp(prefix="aielab-stage11-test-")
    os.environ["AIELAB_DB"] = os.path.join(tmp, "test.db")
    os.environ["AIELAB_SECRET"] = "test-secret-for-stage11-only"
    os.environ.pop("AIELAB_AI_PROVIDER", None)
    os.environ.pop("AIELAB_AI_API_KEY", None)
    conn = dbmod.connect()
    dbmod.init_db(conn)
    server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def req(method, path, token=None, body=None, raw=False):
        r = urllib.request.Request(base + path, method=method)
        if token:
            r.add_header("Authorization", "Bearer " + token)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, data=data, timeout=20) as resp:
                payload = resp.read().decode()
                return resp.status, json.loads(payload) if payload and not raw else payload
        except urllib.error.HTTPError as e:
            payload = e.read().decode()
            try:
                return e.code, json.loads(payload)
            except ValueError:
                return e.code, payload

    # -- health ---------------------------------------------------------
    s, body = req("GET", "/health")
    check("health reports stage 11", body.get("stage") == 11, str(body))

    # -- users ----------------------------------------------------------
    def register(email, username, name):
        s, b = req("POST", "/api/v1/auth/register", body={
            "email": email, "username": username, "password": "secret123",
            "name": name})
        assert s == 201, b
        return b["token"]

    alice = register("alice11@example.com", "alice11", "Alice")
    bob = register("bob11@example.com", "bob11", "Bob")
    s, b = req("GET", "/api/v1/assistant/config")
    check("config requires auth", s == 401, str(s))

    # -- config + tools -------------------------------------------------
    s, cfg = req("GET", "/api/v1/assistant/config", token=alice)
    check("config: local engine, configured, no key",
          s == 200 and cfg["provider"] == "local" and cfg["configured"] is True
          and cfg["api_key_set"] is False, str(cfg))
    s, tools = req("GET", "/api/v1/assistant/tools", token=alice)
    names = {t["name"] for t in tools.get("tools", [])}
    check("tools registry lists the Stage 11 tools",
          {"gear_train", "circuit_voltage_divider", "column_buckling",
           "material_lookup", "project_inspect", "project_propose"} <= names,
          str(names))

    # -- Alice's project with a real structure --------------------------
    s, proj = req("POST", "/api/v1/projects", token=alice,
                  body={"name": "Alice beam bridge"})
    check("Alice creates a project", s == 201, str(proj))
    pid = proj["project"]["id"]
    demo = json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..",
        "workspace", "test-structures", "simply_supported_beam.json")))
    demo.pop("expected", None)
    demo.pop("name", None)
    s, st = req("PUT", f"/api/v1/projects/{pid}/structure", token=alice,
                body={"structure": demo})
    check("Alice saves a structure to the project",
          s == 200 and st["structure"]["version"] == 2, str(st)[:200])
    first_element = demo["elements"][0]["id"]
    orig_section = dict(demo["elements"][0]["section"])

    # -- conversations: create / rename / attach ------------------------
    s, conv = req("POST", "/api/v1/assistant/conversations", token=alice,
                  body={"title": "Beam work"})
    check("create conversation", s == 201 and conv["conversation"]["title"] == "Beam work", str(conv))
    cid = conv["conversation"]["id"]
    s, b = req("PATCH", f"/api/v1/assistant/conversations/{cid}", token=alice,
               body={"title": "Beam work v2"})
    check("rename conversation", s == 200 and b["conversation"]["title"] == "Beam work v2", str(b))
    s, b = req("PATCH", f"/api/v1/assistant/conversations/{cid}", token=alice,
               body={"project_id": pid})
    check("attach own project", s == 200 and b["conversation"]["project_id"] == pid, str(b))
    s, b = req("PATCH", f"/api/v1/assistant/conversations/{cid}", token=bob,
               body={"project_id": pid})
    check("Bob cannot attach Alice's project (404)", s == 404, str(s))
    s, b = req("GET", f"/api/v1/assistant/conversations/{cid}", token=bob)
    check("Bob cannot read Alice's conversation (404)", s == 404, str(s))
    s, b = req("GET", "/api/v1/assistant/conversations", token=bob)
    check("Bob's conversation list is empty",
          s == 200 and b["conversations"] == [], str(b))

    def send(text, token=alice, conv_id=None):
        return req("POST",
                   f"/api/v1/assistant/conversations/{conv_id or cid}/messages",
                   token=token, body={"content": text})

    # 1. engineering question (guidance, no invented numbers) -----------
    s, m = send("what is torque?")
    msg = m["message"]
    check("1. question answered with guidance",
          s == 201 and "torque" in msg["content"].lower()
          and msg["provenance"] == "general guidance"
          and msg["tool_calls"] == [], str(msg)[:200])

    # 2. mechanical calculation via the existing engine ------------------
    s, m = send("calculate the torque for this gearbox: gear train 20 and 40 teeth, 1000 rpm, 10 Nm")
    msg = m["message"]
    check("2. gear train runs the mechanical solver",
          s == 201 and "19" in msg["content"] and "500" in msg["content"]
          and msg["provenance"] == "verified calculation"
          and msg["tool_calls"][0]["tool"] == "gear_train"
          and msg["tool_calls"][0]["status"] == "completed", str(msg)[:300])

    # 3. electrical circuit created and solved ---------------------------
    s, m = send("Create a voltage divider with a 10 V supply, R1 1k, R2 1k")
    msg = m["message"]
    check("3. voltage divider solved by the circuit solver (5 V)",
          s == 201 and "5" in msg["content"]
          and msg["provenance"] == "actual simulation result"
          and msg["tool_calls"][0]["tool"] == "circuit_voltage_divider", str(msg)[:300])

    # 4. structural calculation ------------------------------------------
    s, m = send("column buckling 3 m, 100x100 mm square")
    msg = m["message"]
    check("4. column buckling runs the structural solver",
          s == 201 and "1,827,704" in msg["content"]
          and msg["provenance"] == "verified calculation", str(msg)[:300])

    # 5. material properties ---------------------------------------------
    s, m = send("properties of steel S355")
    msg = m["message"]
    check("5. material properties from the database (E 200 GPa, yield 355)",
          s == 201 and "200" in msg["content"] and "355" in msg["content"]
          and msg["provenance"] == "database value", str(msg)[:300])

    # 11. invalid inputs: missing params -> asked, never invented --------
    s, m = send("gear train with 20 teeth")
    msg = m["message"]
    check("11a. missing params are asked for, not invented",
          s == 201 and "still need" in msg["content"]
          and "teeth on output gear" in msg["content"], str(msg)[:300])
    s, m = send("40 teeth, 1000 rpm, 10 Nm")
    msg = m["message"]
    check("11b. follow-up values complete the calculation (19 N·m)",
          s == 201 and "19" in msg["content"]
          and msg["tool_calls"][0]["status"] == "completed", str(msg)[:300])
    s, m = send("rocket delta-v, Isp 300 s, 100 kg to 200 kg")
    msg = m["message"]
    check("11c. impossible rocket (mf > m0) is refused, no fake delta-v",
          s == 201 and "could not run" in msg["content"]
          and "delta-v" not in msg["content"].lower().replace("rocket delta-v", "")
          and msg["tool_calls"][0]["status"] == "failed", str(msg)[:300])
    s, b = send("", token=alice)
    check("11d. empty message rejected (400)", s == 400, str(b))
    s, b = send("x" * 4001, token=alice)
    check("11e. over-long message rejected (400)", s == 400, str(b))

    # Clarification with suggested defaults ("yes") ----------------------
    s, m = send("Create a voltage divider with a 10 V supply")
    check("clarification asked for the divider resistors",
          s == 201 and "still need" in m["message"]["content"], str(m)[:200])
    s, m = send("yes")
    check("yes applies the suggested 1k resistors (Vout 5 V)",
          s == 201 and "5" in m["message"]["content"]
          and m["message"]["tool_calls"][0]["status"] == "completed", str(m)[:300])

    # 6. project inspection with permission ------------------------------
    s, m = send("inspect my project")
    msg = m["message"]
    check("6. project inspected (structure listed, owner-verified)",
          s == 201 and "Alice beam bridge" in msg["content"]
          and "structure" in msg["content"]
          and msg["tool_calls"][0]["tool"] == "project_inspect", str(msg)[:300])

    # 7. project modification requires approval --------------------------
    s, m = send("change the beam section to 0.2x0.3 m in my project")
    msg = m["message"]
    check("7a. change is proposed, not applied",
          s == 201 and msg["tool_calls"]
          and msg["tool_calls"][0]["status"] == "proposed"
          and msg["tool_calls"][0]["proposal_id"], str(msg)[:300])
    prop_id = msg["tool_calls"][0]["proposal_id"]
    s, st = req("GET", f"/api/v1/projects/{pid}/structure", token=alice)
    check("7b. structure unchanged before approval",
          st["structure"]["elements"][0]["section"] == orig_section
          and st["structure"]["version"] == 2, str(st["structure"]["elements"][0]))
    s, b = req("POST",
               f"/api/v1/assistant/conversations/{cid}/proposals/{prop_id}",
               token=bob, body={"decision": "approve"})
    check("9a. Bob cannot decide Alice's proposal (404)", s == 404, str(b))
    s, b = req("POST",
               f"/api/v1/assistant/conversations/{cid}/proposals/{prop_id}",
               token=alice, body={"decision": "approve"})
    check("7c. approval applies the change", s == 200 and b["proposal"] == "applied", str(b))
    s, st = req("GET", f"/api/v1/projects/{pid}/structure", token=alice)
    new_sec = st["structure"]["elements"][0]["section"]
    check("7d. section is now rectangle 0.2 x 0.3 m, version bumped",
          new_sec.get("type") == "rectangle"
          and approx(new_sec.get("b_m", 0), 0.2) and approx(new_sec.get("h_m", 0), 0.3)
          and st["structure"]["version"] == 3, str(new_sec))
    s, b = req("POST",
               f"/api/v1/assistant/conversations/{cid}/proposals/{prop_id}",
               token=alice, body={"decision": "approve"})
    check("7e. deciding twice is rejected (409)", s == 409, str(b))
    # Deny path.
    s, m = send("change the beam section to 0.5x0.5 m in my project")
    prop2 = m["message"]["tool_calls"][0]["proposal_id"]
    s, b = req("POST",
               f"/api/v1/assistant/conversations/{cid}/proposals/{prop2}",
               token=alice, body={"decision": "deny"})
    check("7f. deny leaves the structure untouched",
          s == 200 and b["proposal"] == "denied", str(b))
    s, st = req("GET", f"/api/v1/projects/{pid}/structure", token=alice)
    check("7g. section still 0.2 x 0.3 m after deny",
          approx(st["structure"]["elements"][0]["section"]["b_m"], 0.2)
          and st["structure"]["version"] == 3, str(st["structure"]["elements"][0]))

    # 9. unauthorized project access --------------------------------------
    s, b = req("GET", f"/api/v1/projects/{pid}", token=bob)
    check("9b. Bob cannot read Alice's project (404)", s == 404, str(b))

    # 8. two users simultaneously -----------------------------------------
    s, conv_b = req("POST", "/api/v1/assistant/conversations", token=bob,
                    body={"title": "Bob chat"})
    cid_b = conv_b["conversation"]["id"]
    results = {}

    def worker(uid, token, conv_id, texts):
        for i, text in enumerate(texts):
            s, m = req("POST",
                       f"/api/v1/assistant/conversations/{conv_id}/messages",
                       token=token, body={"content": text})
            results[(uid, i)] = (s, m.get("message", {}).get("content", ""))

    ta = threading.Thread(target=worker, args=(
        "alice", alice, cid,
        ["properties of titanium Ti-6Al-4V",
         "stall speed 10 kg aircraft, wing area 1 m2, Clmax 1.4",
         "what is buckling?"]))
    tb = threading.Thread(target=worker, args=(
        "bob", bob, cid_b,
        ["properties of copper",
         "gear train 10 and 30 teeth, 500 rpm, 5 Nm",
         "what is lift?"]))
    ta.start()
    tb.start()
    ta.join()
    tb.join()
    check("8a. simultaneous messages all complete",
          all(results[(u, i)][0] == 201 for u in ("alice", "bob") for i in range(3)),
          str(results))
    s, msgs_a = req("GET", f"/api/v1/assistant/conversations/{cid}/messages", token=alice)
    s, msgs_b = req("GET", f"/api/v1/assistant/conversations/{cid_b}/messages", token=bob)
    a_text = " ".join(m["content"] for m in msgs_a["messages"])
    b_text = " ".join(m["content"] for m in msgs_b["messages"])
    check("8b. histories are isolated (no cross-contamination)",
          "titanium" in a_text.lower() and "copper" not in a_text.lower()
          and "copper" in b_text.lower() and "titanium" not in b_text.lower(),
          "alice: " + a_text[:150] + " | bob: " + b_text[:150])

    # 10. AI API failure handled ------------------------------------------
    os.environ["AIELAB_AI_PROVIDER"] = "openai"
    os.environ["AIELAB_AI_MODEL"] = "gpt-4o"
    os.environ.pop("AIELAB_AI_API_KEY", None)
    s, cfg = req("GET", "/api/v1/assistant/config", token=alice)
    check("10a. config reports the named provider as unconfigured",
          cfg["provider"] == "openai" and cfg["configured"] is False
          and cfg["api_key_set"] is False, str(cfg))
    s, m = send("Explain how quantum tunnelling works in a transistor.")
    msg = m["message"]
    check("10b. provider failure falls back to the local engine honestly",
          s == 201 and "unavailable" in msg["content"].lower()
          and "no api key" in msg["content"].lower(), str(msg)[:300])
    s, usage = req("GET", "/api/v1/assistant/usage", token=alice)
    prov_err = [u for u in usage["usage"] if u["status"] == "provider_error"]
    check("10c. provider failure is recorded in usage",
          len(prov_err) >= 1 and prov_err[0]["provider"] == "openai", str(prov_err))
    os.environ.pop("AIELAB_AI_PROVIDER", None)
    os.environ.pop("AIELAB_AI_MODEL", None)

    # Rate limit (unit-level, fresh user) ---------------------------------
    lim = [assistmod.check_rate_limit("rate-test-user") for _ in range(31)]
    check("rate limit trips after 30 messages/minute",
          lim[:30] == [None] * 30 and isinstance(lim[30], str), str(lim[30]))

    # 12. usage and costs --------------------------------------------------
    s, usage_a = req("GET", "/api/v1/assistant/usage", token=alice)
    s, usage_b = req("GET", "/api/v1/assistant/usage", token=bob)
    local_rows = [u for u in usage_a["usage"] if u["provider"] == "local"]
    prov_rows = [u for u in usage_a["usage"] if u["provider"] != "local"]
    check("12a. Alice's usage is recorded (requests, tokens, local $0)",
          usage_a["totals"]["requests"] >= 10
          and usage_a["totals"]["prompt_tokens"] > 0
          and all(u["cost_usd"] == 0.0 for u in local_rows)
          and len(prov_rows) == 1 and prov_rows[0]["cost_usd"] > 0
          and abs(usage_a["totals"]["cost_usd"] - prov_rows[0]["cost_usd"]) < 1e-6,
          str(usage_a["totals"]))
    check("12b. Bob's usage is separate from Alice's",
          usage_b["totals"]["requests"] == 3
          and usage_b["totals"]["requests"] != usage_a["totals"]["requests"],
          str(usage_b["totals"]))

    # Conversation deletion ------------------------------------------------
    s, conv2 = req("POST", "/api/v1/assistant/conversations", token=alice,
                   body={"title": "to delete"})
    cid2 = conv2["conversation"]["id"]
    send("what is lift?", conv_id=cid2)
    s, b = req("DELETE", f"/api/v1/assistant/conversations/{cid2}", token=alice)
    check("delete conversation", s == 200 and b.get("deleted") is True, str(b))
    s, b = req("GET", f"/api/v1/assistant/conversations/{cid2}", token=alice)
    check("deleted conversation is gone (404)", s == 404, str(b))

    # Persistence: messages survive a fresh read ---------------------------
    s, msgs = req("GET", f"/api/v1/assistant/conversations/{cid}/messages", token=alice)
    user_msgs = [m for m in msgs["messages"] if m["role"] == "user"]
    check("conversation history persists",
          s == 200 and len(user_msgs) >= 12, f"{len(user_msgs)} user messages")

    server.shutdown()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    if FAIL:
        print("FAILURES:")
        for f in FAIL:
            print("  - " + f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
