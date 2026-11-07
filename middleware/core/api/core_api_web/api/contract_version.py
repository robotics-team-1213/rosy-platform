"""The one place the code names the live API contract version (the reference header is the source).

`tools/harness/api_reserve.py bump` rewrites CONTRACT; test_protocol_version_alignment keeps it equal to the
`**Version:**` header of docs/reference/ROSY API & Protocol Reference.md. Feature tests do not pin the version.
"""

CONTRACT = "ROSY-API-REF-001 v1.373"
