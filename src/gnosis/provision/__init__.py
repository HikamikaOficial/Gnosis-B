"""GNOSIS production provisioning (F-17 Stage 8).

This package turns the qualified architecture into a reproducible, fail-closed
Windows deployment. It runs ONLY as trusted maintenance code at install / update
/ rollback / uninstall time; it is NOT imported by the Publisher runtime, so it
never enters the publisher import closure.
"""
