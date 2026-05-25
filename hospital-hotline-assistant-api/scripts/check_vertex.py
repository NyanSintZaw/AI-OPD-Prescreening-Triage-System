"""Direct sanity check for Vertex AI access.

Run from the API directory:
    python scripts/check_vertex.py
"""

import os
import sys
import pathlib


REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
CRED_PATH = REPO_DIR / "phoenix_gcp_credentials.json"

if not CRED_PATH.exists():
    print(f"FAIL: credentials file not found at {CRED_PATH}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(CRED_PATH)
print(f"creds: {CRED_PATH}")

try:
    from google import genai
except Exception as exc:
    print(f"FAIL importing google.genai: {type(exc).__name__}: {exc}")
    sys.exit(1)

PROJECT = "phoenix-487410"
LOCATION = "us-central1"
MODEL = "gemini-2.5-flash"

print(f"project={PROJECT} location={LOCATION} model={MODEL}")

try:
    client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
except Exception as exc:
    print(f"FAIL constructing client: {type(exc).__name__}: {exc}")
    sys.exit(1)

prompt = "Reply with the single word OK if you can read this."

try:
    response = client.models.generate_content(model=MODEL, contents=prompt)
except Exception as exc:
    print(f"FAIL calling generate_content: {type(exc).__name__}: {exc}")
    sys.exit(1)

text = getattr(response, "text", None)
print("OK. response.text =", repr(text)[:300])
