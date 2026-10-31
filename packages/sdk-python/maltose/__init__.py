"""MUP v0.3 SDK: strict schemas; no dynamic executable UI."""
import json
from importlib.resources import files
from uuid import uuid4
from jsonschema import Draft202012Validator, FormatChecker
PROTOCOL = "mup/0.3"
def validate(message, name="command"):
    schema = json.loads(files(__package__).joinpath(f"schemas/{name}.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(message)
    return message

def command(name, payload=None, *, session_id=None, request_id=None, idempotency_key=None):
    msg = dict(protocol=PROTOCOL, message_id=str(uuid4()), session_id=session_id or str(uuid4()), request_id=request_id or str(uuid4()), type="command", name=name, payload=payload or {})
    if idempotency_key: msg['idempotency_key'] = idempotency_key
    return validate(msg)

# Imported last to keep schema helpers available during client module initialization.
from .client import Client, MUPException
