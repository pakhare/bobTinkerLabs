"""
setup_wxo_security.py – One-time setup helper for watsonx Orchestrate chat security.

Run this once from the ai-task-optimizer directory:
    python setup_wxo_security.py

What it does
------------
1. Checks that config/wxo_private.pem and config/wxo_public.pem exist
   (generates a new 4096-bit RSA key pair if they do not).
2. Prints the public key and exact instructions for registering it in
   the watsonx Orchestrate UI.

Why this is required
--------------------
IBM watsonx Orchestrate requires embedded chat pages to authenticate every
user via a signed RS256 JWT.  The widget will refuse to initialise and show
an authentication error if no valid JWT is provided.

The flow is:
  1. You generate an RSA key pair (this script does that).
  2. You register the PUBLIC key once in the watsonx Orchestrate UI.
  3. The app signs JWTs with the PRIVATE key at runtime (wxo_jwt_server.py).
  4. The widget calls onGetUserToken() → fetches the JWT from /token → passes
     it to IBM → IBM validates it against the registered public key → chat works.
"""
from pathlib import Path

CONFIG = Path(__file__).parent / "config"
PRIV   = CONFIG / "wxo_private.pem"
PUB    = CONFIG / "wxo_public.pem"


def generate_keys():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    print("Generating 4096-bit RSA key pair …")
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    PRIV.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    PUB.write_bytes(key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    print(f"  Private key → {PRIV}")
    print(f"  Public  key → {PUB}")


def main():
    if not PRIV.exists() or not PUB.exists():
        generate_keys()
    else:
        print(f"Keys already exist:\n  {PRIV}\n  {PUB}")

    pub_text = PUB.read_text()

    print("\n" + "=" * 70)
    print("NEXT STEP – Register the public key in watsonx Orchestrate")
    print("=" * 70)
    print("""
1. Open IBM watsonx Orchestrate in your browser.
2. Navigate to:  Deploy → Web chat → your agent → Security
3. Click  "Add public key"  (or "Configure security").
4. Paste the PUBLIC KEY shown below into the input field and save.

Once saved, the app can sign JWTs that IBM will accept and the
authentication error will disappear.
""")
    print("─" * 70)
    print("PUBLIC KEY  (copy everything including BEGIN/END lines):")
    print("─" * 70)
    print(pub_text)
    print("─" * 70)
    print("\nDone.  Now restart the AI Task Optimizer app.")


if __name__ == "__main__":
    main()
