"""Preenche os placeholders de workflows-json/*.json (valores do .env + IDs das credenciais já
criadas na UI do n8n) e importa no container. Reimportar sobrescreve (IDs fixos)."""
import json, subprocess
from pathlib import Path

ROOT = Path(__file__).parent
KEYS = ["SHEET_ID", "GROUP_ID", "NUMERO_DO_BOT", "BOT_LID", "ALERT_EMAIL", "HOOK_SECRET"]
CRED_TYPES = {"CRED_GOOGLE": "googleApi", "CRED_WAHA": "httpHeaderAuth", "CRED_SMTP": "smtp"}


def n8n(cmd, stdin=None):
    return subprocess.run(["docker", "compose", "exec", "-T", "-u", "node", "n8n", "sh", "-c", cmd],
                          cwd=ROOT, input=stdin, capture_output=True, text=True, encoding="utf-8", check=True).stdout


env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
vals = {k: env.get(k, "").strip() for k in KEYS}
missing = [k for k, v in vals.items() if not v]
assert not missing, f"preencha no .env: {missing}"
assert vals["GROUP_ID"].endswith("@g.us"), "GROUP_ID deve terminar em @g.us"
assert vals["NUMERO_DO_BOT"].isdigit(), "NUMERO_DO_BOT: só dígitos com DDI"
assert vals["BOT_LID"].isdigit(), "BOT_LID: só os dígitos de me.lid (sem @lid)"

creds = json.loads(n8n("n8n export:credentials --all --output=/tmp/c.json >/dev/null && cat /tmp/c.json && rm /tmp/c.json"))
for ph, type_ in CRED_TYPES.items():
    found = [c["id"] for c in creds if c["type"] == type_]
    assert len(found) == 1, f"esperava 1 credencial do tipo {type_} no n8n, achei {len(found)}"
    vals[ph] = found[0]

for f in sorted((ROOT / "workflows-json").glob("*.json")):
    txt = f.read_text(encoding="utf-8")
    for k, v in vals.items():
        txt = txt.replace(f"__{k}__", json.dumps(v)[1:-1])
    n8n("cat > /tmp/wf.json && n8n import:workflow --input=/tmp/wf.json && rm /tmp/wf.json", stdin=txt)
    print("importado:", f.name)
