"""Validate OpenAPI documents and resolve their shared local references."""
from pathlib import Path

import yaml
from openapi_spec_validator import validate


def main():
    root = Path(__file__).resolve().parents[1] / "contracts"
    documents = sorted(root.glob("*.openapi.yaml"))
    for path in documents:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate(document, base_uri=path.as_uri())
        print(f"OK {path.name}")
    print(f"Validated {len(documents)} OpenAPI documents (including local references).")


if __name__ == "__main__":
    main()
