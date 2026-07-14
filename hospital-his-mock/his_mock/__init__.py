"""Mock hospital HIS API.

Simulates the hospital's side of the integration: their visit database
stays behind this service and is only reachable through the REST API —
never as a shared database. The triage backend talks to it through
``HttpHisAdapter`` exactly as it will talk to the real HIS.
"""
