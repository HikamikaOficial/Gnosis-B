# ADR-0035 — Stage and activate composed releases without replacing accounts

Date: 2026-09-27
Status: implemented in maintenance; OS qualification pending

The installed V1 application has a protected composed record in stable state.
Staging via the installation entry would replace this record while the previous
service still runs, and reinstalling would risk credentials and existing work.

The maintenance update therefore stages a distinct release with the existing
Provisioner.stage_release, deploys its application without writing the active
composed record, and measures the result. Claude's approved native binary is
copied inside the protected runtime and included in the same deployment identity.
The active installation is freshly verified both before and after staging.

Activation checks the full recorded old/new configurations, source identities,
current deployment and staged tree. It snapshots stable configuration/identity
records in the protected maintenance directory before stopping the service. It
uses the existing activate_release operation, creates the composed record for
the freshly observed final identity, verifies it, and starts the service before
updating maintenance configuration. Accounts, DPAPI credentials, plans and task
histories are retained. An ordinary activation failure restores and verifies the
old release; failed restoration is explicitly recovery-required, never success.

An interrupted maintenance process retains an activating journal and rollback
snapshots. This initial implementation does not claim automatic recovery from a
hard process kill during switching; that recovery remains an acceptance item.
No provider is invoked and no task is accepted by maintenance staging/activation.
